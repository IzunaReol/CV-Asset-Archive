import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.errors import AppError
from app.routers import tags


def test_default_tag_cannot_be_deleted(monkeypatch):
    delete_one = AsyncMock()
    database = SimpleNamespace(
        tag_definitions=SimpleNamespace(
            find_one=AsyncMock(return_value={"key": "status", "built_in": True}),
            delete_one=delete_one,
        ),
        assets=SimpleNamespace(count_documents=AsyncMock()),
    )
    monkeypatch.setattr(tags, "db", database)

    with pytest.raises(AppError) as exc_info:
        asyncio.run(tags.delete_tag("status", SimpleNamespace(), {"id": "admin"}))

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "BUILT_IN_TAG_PROTECTED"
    delete_one.assert_not_awaited()
    database.assets.count_documents.assert_not_awaited()


def test_custom_unused_tag_can_be_deleted(monkeypatch):
    delete_one = AsyncMock(return_value=SimpleNamespace(deleted_count=1))
    database = SimpleNamespace(
        tag_definitions=SimpleNamespace(
            find_one=AsyncMock(return_value={"key": "custom", "built_in": False}),
            delete_one=delete_one,
        ),
        assets=SimpleNamespace(count_documents=AsyncMock(return_value=0)),
    )
    audit = AsyncMock()
    monkeypatch.setattr(tags, "db", database)
    monkeypatch.setattr(tags, "record_audit", audit)

    asyncio.run(
        tags.delete_tag(
            "custom",
            SimpleNamespace(state=SimpleNamespace(request_id="request-1")),
            {"id": "admin"},
        )
    )

    delete_one.assert_awaited_once_with({"key": "custom"})
    assert audit.call_args.kwargs["action"] == "tag_definition.deleted"
