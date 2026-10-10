from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.errors import AppError
from app.routers import admin
from app.schemas import AssetType


def test_normalize_extensions_trims_prefix_and_duplicates():
    assert admin.normalize_extensions([" JPG ", ".jpg", "png", ""]) == [".jpg", ".png"]


def test_fixed_role_uses_predefined_menu_permissions():
    body = admin.UserCreate(username="viewer-user", password="password123", roles=["viewer"])

    assert body.menu_permissions == ["overview", "library", "datasets", "relations", "lineage", "downloads"]


def test_reusable_role_rejects_action_without_corresponding_menu():
    with pytest.raises(ValueError, match="缺少对应菜单"):
        admin.RoleTemplateBody(
            name="素材只读角色", menu_permissions=["overview"], action_permissions=["asset_edit"],
        )


@pytest.mark.asyncio
async def test_create_reusable_role_persists_permissions(monkeypatch):
    role_templates = SimpleNamespace(insert_one=AsyncMock())
    monkeypatch.setattr(admin, "db", SimpleNamespace(role_templates=role_templates))
    monkeypatch.setattr(admin, "record_audit", AsyncMock())
    request = SimpleNamespace(state=SimpleNamespace(request_id="request"))
    body = admin.RoleTemplateBody(
        name="质检负责人", menu_permissions=["overview", "library"], action_permissions=["asset_edit"],
    )

    result = await admin.create_role_template(body, request, {"id": "admin", "username": "admin"})

    assert result["name"] == "质检负责人"
    assert result["menu_permissions"] == ["overview", "library"]
    role_templates.insert_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_bound_reusable_role_reports_usernames(monkeypatch):
    class Cursor:
        def limit(self, *_): return self
        async def to_list(self, **_): return [{"username": "zhangsan"}, {"username": "lisi"}]
    role_templates = SimpleNamespace(find_one=AsyncMock(return_value={"id": "role-1", "name": "质检"}))
    users = SimpleNamespace(find=lambda *_args, **_kwargs: Cursor())
    monkeypatch.setattr(admin, "db", SimpleNamespace(role_templates=role_templates, users=users))
    request = SimpleNamespace(state=SimpleNamespace(request_id="request"))

    with pytest.raises(AppError, match="zhangsan、lisi") as error:
        await admin.delete_role_template("role-1", request, {"id": "admin", "username": "admin"})

    assert error.value.code == "ROLE_IN_USE"


def test_custom_role_keeps_unique_selected_menu_permissions():
    body = admin.UserCreate(
        username="custom-user",
        password="password123",
        roles=["custom"],
        menu_permissions=["library", "datasets", "library"],
    )

    assert body.menu_permissions == ["library", "datasets"]


def test_custom_role_requires_at_least_one_menu_permission():
    with pytest.raises(ValueError, match="至少选择一个菜单权限"):
        admin.UserCreate(username="custom-user", password="password123", roles=["custom"])


def test_custom_action_permission_requires_corresponding_menu():
    with pytest.raises(ValueError, match="对应菜单"):
        admin.UserCreate(
            username="custom-user", password="password123", roles=["custom"],
            menu_permissions=["library"], action_permissions=["format_manage"],
        )


@pytest.mark.asyncio
async def test_admin_user_cannot_be_updated_or_deleted(monkeypatch):
    users = SimpleNamespace(find_one=AsyncMock(return_value={"id": "admin", "username": "admin"}))
    monkeypatch.setattr(admin, "db", SimpleNamespace(users=users))
    body = admin.UserUpdate(username="admin", roles=["admin"], status="active")
    request = SimpleNamespace(state=SimpleNamespace(request_id="request"))

    with pytest.raises(AppError) as update_error:
        await admin.update_user("admin", body, request, {"id": "admin"})
    with pytest.raises(AppError) as delete_error:
        await admin.delete_user("admin", request, {"id": "admin"})

    assert update_error.value.code == "ADMIN_USER_PROTECTED"
    assert delete_error.value.code == "ADMIN_USER_PROTECTED"


@pytest.mark.asyncio
async def test_updating_user_revokes_refresh_sessions(monkeypatch):
    target = {
        "id": "user-1", "username": "old-name", "roles": ["viewer"],
        "menu_permissions": [], "action_permissions": [], "status": "active",
    }
    updated = {**target, "username": "new-name"}
    users = SimpleNamespace(
        find_one=AsyncMock(side_effect=[target, None, updated]),
        update_one=AsyncMock(),
    )
    refresh_sessions = SimpleNamespace(delete_many=AsyncMock())
    monkeypatch.setattr(admin, "db", SimpleNamespace(users=users, refresh_sessions=refresh_sessions))
    monkeypatch.setattr(admin, "record_audit", AsyncMock())
    request = SimpleNamespace(state=SimpleNamespace(request_id="request"))

    result = await admin.update_user(
        "user-1",
        admin.UserUpdate(username="new-name", roles=["viewer"], status="active"),
        request,
        {"id": "admin"},
    )

    assert result["username"] == "new-name"
    refresh_sessions.delete_many.assert_awaited_once_with({"user_id": "user-1"})


@pytest.mark.asyncio
async def test_extension_in_use_cannot_be_removed(monkeypatch):
    monkeypatch.setattr(
        admin,
        "db",
        SimpleNamespace(assets=SimpleNamespace(count_documents=AsyncMock(return_value=1))),
    )

    with pytest.raises(AppError) as error:
        await admin.ensure_extensions_removable(AssetType.IMAGE.value, [".jpg"])

    assert error.value.code == "FORMAT_EXTENSION_IN_USE"


@pytest.mark.asyncio
async def test_audit_export_contains_request_context_and_utf8_bom(monkeypatch):
    class Cursor:
        def __init__(self, items):
            self.items = items
        def sort(self, *args):
            return self
        def limit(self, *args):
            return self
        def __aiter__(self):
            self.iterator = iter(self.items)
            return self
        async def __anext__(self):
            try:
                return next(self.iterator)
            except StopIteration:
                raise StopAsyncIteration

    audit_logs = SimpleNamespace(find=lambda query: Cursor([{
        "created_at": "2026-10-09", "actor_username": "admin", "action": "asset.created",
        "object_type": "asset", "object_name": "测试.jpg", "outcome": "success",
        "response_status": 201, "client_ip": "127.0.0.1", "request_id": "request-1",
        "changes": {"filename": "测试.jpg"},
    }]))
    monkeypatch.setattr(admin, "db", SimpleNamespace(audit_logs=audit_logs))

    response = await admin.export_audit_logs({"id": "admin"}, "", None, None, None, None, None)
    body = b"".join([chunk async for chunk in response.body_iterator])

    assert body.startswith(b"\xef\xbb\xbf")
    text = body.decode("utf-8")
    assert "客户端IP" in text
    assert "测试.jpg" in text


@pytest.mark.asyncio
async def test_built_in_format_can_be_updated_but_protected_extension_cannot_be_removed(monkeypatch):
    formats = SimpleNamespace(
        find_one=AsyncMock(
            return_value={
                "asset_type": "image",
                "built_in": True,
                "extensions": [".jpg", ".png"],
                "protected_extensions": [".jpg", ".png"],
            }
        )
    )
    monkeypatch.setattr(admin, "db", SimpleNamespace(format_definitions=formats))

    with pytest.raises(AppError) as error:
        await admin.update_format_definition(
            AssetType.IMAGE,
            admin.FormatUpdate(extensions=[".jpg"]),
            SimpleNamespace(state=SimpleNamespace(request_id="request")),
            {"id": "admin"},
        )

    assert error.value.code == "BUILT_IN_FORMAT_PROTECTED"


@pytest.mark.asyncio
async def test_built_in_format_allows_adding_extension_and_editing_remark(monkeypatch):
    current = {
        "asset_type": "image",
        "built_in": True,
        "extensions": [".jpg", ".png"],
        "protected_extensions": [".jpg", ".png"],
    }
    updated = {**current, "extensions": [".jpg", ".png", ".jxl"], "remark": "常用图片"}
    formats = SimpleNamespace(
        find_one=AsyncMock(side_effect=[current, None, updated]),
        update_one=AsyncMock(),
    )
    monkeypatch.setattr(admin, "db", SimpleNamespace(format_definitions=formats))
    monkeypatch.setattr(admin, "record_audit", AsyncMock())

    result = await admin.update_format_definition(
        AssetType.IMAGE,
        admin.FormatUpdate(remark="常用图片", extensions=[".jpg", ".png", ".jxl"]),
        SimpleNamespace(state=SimpleNamespace(request_id="request")),
        {"id": "admin", "username": "admin"},
    )

    assert result["extensions"] == [".jpg", ".png", ".jxl"]
    formats.update_one.assert_awaited_once()
