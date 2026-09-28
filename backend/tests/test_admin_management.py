from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.errors import AppError
from app.routers import admin
from app.schemas import AssetType


def test_normalize_extensions_trims_prefix_and_duplicates():
    assert admin.normalize_extensions([" JPG ", ".jpg", "png", ""]) == [".jpg", ".png"]


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
async def test_extension_in_use_cannot_be_removed(monkeypatch):
    monkeypatch.setattr(
        admin,
        "db",
        SimpleNamespace(assets=SimpleNamespace(count_documents=AsyncMock(return_value=1))),
    )

    with pytest.raises(AppError) as error:
        await admin.ensure_extensions_removable(AssetType.IMAGE.value, [".jpg"])

    assert error.value.code == "FORMAT_EXTENSION_IN_USE"
