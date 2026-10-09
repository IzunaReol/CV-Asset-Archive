import asyncio

import pytest

from app.dependencies import (
    ensure_action_access, ensure_data_management_access, require_action, require_menu,
    require_roles, require_scoped_action,
)
from app.schemas import Role
from app.errors import AppError
from app.permissions import effective_action_permissions


def test_data_manager_and_admin_have_destructive_access():
    ensure_data_management_access({"roles": ["admin"]})
    ensure_data_management_access({"roles": ["data_manager"]})


def test_regular_write_roles_do_not_have_destructive_access():
    for role in ("annotator", "ml_engineer"):
        try:
            ensure_data_management_access({"roles": [role]})
        except AppError as exc:
            assert exc.status_code == 403
            assert exc.code == "PERMISSION_DENIED"
        else:
            raise AssertionError(f"{role} 不应拥有破坏性操作权限")


def test_custom_role_can_use_explicitly_granted_menu_dependency():
    dependency = require_roles(Role.ADMIN, menu_permissions=("admin",))

    result = asyncio.run(dependency({"roles": ["custom"], "menu_permissions": ["admin"]}))

    assert result["roles"] == ["custom"]


def test_custom_menu_permission_does_not_grant_write_action():
    dependency = require_action("format_manage")
    try:
        asyncio.run(dependency({"roles": ["custom"], "menu_permissions": ["formats"], "action_permissions": []}))
    except AppError as exc:
        assert exc.status_code == 403
        assert exc.code == "PERMISSION_DENIED"
    else:
        raise AssertionError("只有菜单权限时不应允许修改格式")


def test_explicit_custom_action_permission_allows_operation():
    user = {"roles": ["custom"], "menu_permissions": ["formats"], "action_permissions": ["format_manage"]}
    assert asyncio.run(require_action("format_manage")(user)) == user


def test_custom_action_permission_requires_its_menu_at_runtime():
    user = {"roles": ["custom"], "menu_permissions": ["library"], "action_permissions": ["format_manage"]}
    try:
        asyncio.run(require_action("format_manage")(user))
    except AppError as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("没有格式管理菜单时不应执行格式管理操作")


def test_fixed_viewer_can_read_but_cannot_write():
    user = {"roles": ["viewer"]}
    assert asyncio.run(require_menu("library")(user)) == user
    try:
        asyncio.run(require_action("asset_upload")(user))
    except AppError as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("只读访客不应拥有上传权限")


def test_export_action_also_requires_source_menu():
    user = {
        "roles": ["custom"], "menu_permissions": ["downloads"],
        "action_permissions": ["export_create"],
    }
    try:
        asyncio.run(require_scoped_action("export_create", "datasets")(user))
    except AppError as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("没有数据集菜单时不应允许数据集导出")


def test_overwrite_requires_asset_delete_permission():
    user = {
        "roles": ["custom"], "menu_permissions": ["library"],
        "action_permissions": ["asset_upload"],
    }
    try:
        ensure_action_access(user, "asset_delete")
    except AppError as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("只有上传权限时不应允许覆盖素材")


def test_legacy_dataset_manage_expands_to_granular_permissions():
    permissions = effective_action_permissions({
        "roles": ["custom"], "action_permissions": ["dataset_manage"],
    })

    assert {
        "dataset_create_edit", "dataset_members_manage", "dataset_version_publish",
        "dataset_version_restore", "dataset_delete", "dataset_model_manage",
    } <= permissions


def test_system_log_menu_can_be_granted_without_user_management():
    user = {"roles": ["custom"], "menu_permissions": ["logs"], "action_permissions": []}

    assert asyncio.run(require_menu("logs")(user)) == user
    with pytest.raises(AppError):
        asyncio.run(require_action("user_manage")(user))
