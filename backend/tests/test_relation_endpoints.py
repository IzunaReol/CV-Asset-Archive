from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.errors import AppError
from app.routers import relations
from app.schemas import RelationBatchRequest, RelationCreate, RevokeRelationRequest


class Cursor:
    def __init__(self, items):
        self.items = items

    def sort(self, *args):
        return self

    def skip(self, *args):
        return self

    def limit(self, *args):
        return self

    async def to_list(self, **kwargs):
        return self.items

    def __aiter__(self):
        self.iterator = iter(self.items)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration:
            raise StopAsyncIteration


def request():
    return SimpleNamespace(state=SimpleNamespace(request_id="request-1"))


def user():
    return {"id": "user-1", "username": "管理员"}


@pytest.mark.asyncio
async def test_create_relation_increments_revision_and_records_audit(monkeypatch):
    store = SimpleNamespace(
        find_one=AsyncMock(return_value={"revision": 2, "status": "revoked"}),
        insert_one=AsyncMock(),
    )
    validate = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(relations, "db", SimpleNamespace(relations=store))
    monkeypatch.setattr(relations, "validate_relation", validate)
    monkeypatch.setattr(relations, "record_audit", audit)
    monkeypatch.setattr(relations, "new_id", lambda: "relation-3")

    result = await relations.create_relation(
        RelationCreate(source_id="model-1", target_id="version-1", relation_type="trained_on"),
        request(), user(),
    )

    assert result["id"] == "relation-3"
    assert result["revision"] == 3
    store.insert_one.assert_awaited_once()
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_relation_rejects_active_duplicate(monkeypatch):
    store = SimpleNamespace(find_one=AsyncMock(return_value={"revision": 1, "status": "active"}))
    monkeypatch.setattr(relations, "db", SimpleNamespace(relations=store))
    monkeypatch.setattr(relations, "validate_relation", AsyncMock())

    with pytest.raises(AppError) as exc_info:
        await relations.create_relation(
            RelationCreate(source_id="model-1", target_id="version-1", relation_type="trained_on"),
            request(), user(),
        )
    assert exc_info.value.code == "RELATION_EXISTS"


@pytest.mark.asyncio
async def test_create_relations_reports_partial_failure(monkeypatch):
    created = AsyncMock(side_effect=[{"id": "ok"}, AppError(422, "BAD", "无效关系")])
    monkeypatch.setattr(relations, "create_relation", created)
    body = RelationBatchRequest(relations=[
        {"source_id": "a1", "target_id": "i1", "relation_type": "annotates"},
        {"source_id": "a2", "target_id": "i2", "relation_type": "annotates"},
    ])

    result = await relations.create_relations(body, request(), user())

    assert result["succeeded"] == [{"id": "ok"}]
    assert result["failed"][0]["code"] == "BAD"


@pytest.mark.asyncio
async def test_preview_relations_groups_all_results(monkeypatch):
    preview = AsyncMock(side_effect=[
        {"code": "READY"}, {"code": "RELATION_EXISTS"}, {"code": "SELF_RELATION"},
    ])
    monkeypatch.setattr(relations, "preview_relation_item", preview)
    body = RelationBatchRequest(relations=[
        {"source_id": f"a{index}", "target_id": f"i{index}", "relation_type": "annotates"}
        for index in range(3)
    ])

    result = await relations.preview_relations(body, user())

    assert result["counts"] == {"ready": 1, "existing": 1, "invalid": 1}


@pytest.mark.asyncio
async def test_get_relation_returns_resolved_objects(monkeypatch):
    relation_store = SimpleNamespace(find_one=AsyncMock(return_value={
        "id": "r1", "source_id": "a1", "target_id": "v1", "status": "active",
    }))
    assets = SimpleNamespace(find_one=AsyncMock(side_effect=[{"id": "a1", "name": "标注"}, None]))
    versions = SimpleNamespace(find_one=AsyncMock(return_value={"id": "v1", "name": "训练集 v1"}))
    empty = SimpleNamespace(find_one=AsyncMock(return_value=None))
    monkeypatch.setattr(relations, "db", SimpleNamespace(
        relations=relation_store, assets=assets, dataset_versions=versions,
        datasets=empty, collections=empty,
    ))

    result = await relations.get_relation("r1", user())

    assert result["source"]["name"] == "标注"
    assert result["target"]["name"] == "训练集 v1"


@pytest.mark.asyncio
async def test_get_relation_rejects_missing_relation(monkeypatch):
    monkeypatch.setattr(relations, "db", SimpleNamespace(
        relations=SimpleNamespace(find_one=AsyncMock(return_value=None))
    ))
    with pytest.raises(AppError) as exc_info:
        await relations.get_relation("missing", user())
    assert exc_info.value.code == "RELATION_NOT_FOUND"


@pytest.mark.asyncio
async def test_revoke_relation_is_idempotent(monkeypatch):
    revoked = {"id": "r1", "status": "revoked"}
    monkeypatch.setattr(relations, "db", SimpleNamespace(
        relations=SimpleNamespace(find_one=AsyncMock(return_value=revoked))
    ))
    assert await relations.revoke_relation(
        "r1", RevokeRelationRequest(reason="重复请求"), request(), user()
    ) == revoked


@pytest.mark.asyncio
async def test_revoke_active_relation_updates_and_audits(monkeypatch):
    active = {"id": "r1", "source_id": "model-1", "target_id": "version-1", "relation_type": "trained_on", "status": "active"}
    revoked = {**active, "status": "revoked", "revoke_reason": "不再使用"}
    store = SimpleNamespace(
        find_one=AsyncMock(side_effect=[active, revoked]),
        update_one=AsyncMock(),
    )
    audit = AsyncMock()
    monkeypatch.setattr(relations, "db", SimpleNamespace(
        relations=store, collections=SimpleNamespace(find_one=AsyncMock(return_value=None))
    ))
    monkeypatch.setattr(relations, "record_audit", audit)

    result = await relations.revoke_relation(
        "r1", RevokeRelationRequest(reason="不再使用"), request(), user()
    )

    assert result["status"] == "revoked"
    store.update_one.assert_awaited_once()
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_preview_revoke_relation_returns_dataset_effects(monkeypatch):
    relation = {"id": "r1", "source_id": "a1", "target_id": "i1", "relation_type": "annotates", "status": "active"}
    effect = AsyncMock(return_value=[{"dataset_id": "d1", "removed": ["a1"]}])
    monkeypatch.setattr(relations, "db", SimpleNamespace(
        relations=SimpleNamespace(find_one=AsyncMock(return_value=relation))
    ))
    monkeypatch.setattr(relations, "annotation_dataset_effect", effect)

    result = await relations.preview_revoke_relation("r1", user())

    assert result["dataset_effects"][0]["dataset_id"] == "d1"
    effect.assert_awaited_once_with("a1", "i1", exclude_relation_id="r1")


@pytest.mark.asyncio
async def test_list_relations_applies_filters_and_resolves_names(monkeypatch):
    relation = {
        "id": "r1", "source_id": "a1", "target_id": "v1", "relation_type": "trained_on",
        "status": "active", "created_by_name": "管理员",
    }
    relation_store = SimpleNamespace(
        count_documents=AsyncMock(return_value=1),
        find=lambda *args, **kwargs: Cursor([relation]),
    )
    assets = SimpleNamespace(
        distinct=AsyncMock(return_value=["a1"]),
        find_one=AsyncMock(side_effect=[{"id": "a1", "name": "模型", "type": "model"}, None]),
    )
    versions = SimpleNamespace(
        distinct=AsyncMock(side_effect=[["v1"], ["v1"]]),
        find_one=AsyncMock(return_value={"id": "v1", "name": "训练集 v1", "kind": "dataset_version"}),
    )
    collections = SimpleNamespace(distinct=AsyncMock(return_value=[]), find_one=AsyncMock(return_value=None))
    monkeypatch.setattr(relations, "db", SimpleNamespace(
        relations=relation_store, assets=assets, dataset_versions=versions, collections=collections,
    ))

    result = await relations.list_relations(
        user(), q="训练", relation_type="trained_on", created_by="管理", status="active",
        created_from="2026-01-01T00:00:00", created_to="2026-12-31T23:59:59",
        page=1, page_size=10,
    )

    assert result["total"] == 1
    assert result["items"][0]["source_name"] == "模型"
    assert result["items"][0]["target_name"] == "训练集 v1"


@pytest.mark.asyncio
async def test_list_relations_rejects_invalid_date(monkeypatch):
    monkeypatch.setattr(relations, "db", SimpleNamespace(
        dataset_versions=SimpleNamespace(distinct=AsyncMock(return_value=[]))
    ))
    with pytest.raises(AppError) as exc_info:
        await relations.list_relations(user(), created_from="not-a-date")
    assert exc_info.value.code == "INVALID_DATE_FILTER"


@pytest.mark.asyncio
async def test_relation_graph_returns_connected_assets(monkeypatch):
    relation = {
        "id": "r1", "source_id": "a1", "target_id": "i1",
        "relation_type": "annotates", "status": "active",
    }
    asset_rows = [
        {"id": "a1", "name": "标注", "type": "annotation"},
        {"id": "i1", "name": "图片", "type": "image"},
    ]
    assets = SimpleNamespace(
        find_one=AsyncMock(side_effect=[asset_rows[0], asset_rows[1]]),
        find=lambda *args, **kwargs: Cursor(asset_rows),
    )
    empty = SimpleNamespace(
        find_one=AsyncMock(return_value=None),
        find=lambda *args, **kwargs: Cursor([]),
    )
    versions = SimpleNamespace(
        find_one=AsyncMock(return_value=None),
        find=lambda *args, **kwargs: Cursor([]),
    )
    monkeypatch.setattr(relations, "db", SimpleNamespace(
        relations=SimpleNamespace(find=lambda *args, **kwargs: Cursor([relation])),
        assets=assets, collections=empty, datasets=empty, dataset_versions=versions,
    ))

    result = await relations.relation_graph("a1", user(), depth=1, member_limit=0)

    assert {item["id"] for item in result["nodes"]} == {"a1", "i1"}
    assert result["edges"][0]["relation_type"] == "annotates"
    assert result["member_total"] == 0
