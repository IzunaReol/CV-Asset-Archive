import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.errors import AppError
from app.routers import tags
from app.schemas import TagDefinitionCreate, TagDefinitionUpdate, TagValueCreate
from pydantic import ValidationError


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


@pytest.mark.parametrize("values", [["漏件", " 漏件 "], ["Defect", "defect"]])
def test_tag_definition_rejects_duplicate_values(values):
    with pytest.raises(ValidationError, match="标签值不能重复"):
        TagDefinitionCreate(key="defect", name="缺陷", values=values)
    with pytest.raises(ValidationError, match="标签值不能重复"):
        TagDefinitionUpdate(name="缺陷", values=values)


def test_add_tag_value_and_reject_duplicate(monkeypatch):
    document = {"key": "defect", "values": ["漏件"]}
    async def find_one(_query):
        return document.copy()
    async def update_one(_query, changes):
        document.update(changes["$set"])
        return SimpleNamespace(modified_count=1)
    audit = AsyncMock()
    monkeypatch.setattr(tags, "db", SimpleNamespace(tag_definitions=SimpleNamespace(
        find_one=find_one, update_one=update_one,
    )))
    monkeypatch.setattr(tags, "record_audit", audit)
    request = SimpleNamespace(state=SimpleNamespace(request_id="request-1"))
    result = asyncio.run(tags.add_tag_value("defect", TagValueCreate(value=" 错件 "), request, {"id": "admin"}))
    assert result["values"] == ["漏件", "错件"]
    with pytest.raises(AppError) as exc_info:
        asyncio.run(tags.add_tag_value("defect", TagValueCreate(value="错件"), request, {"id": "admin"}))
    assert exc_info.value.code == "TAG_VALUE_EXISTS"
    audit.assert_awaited_once()
