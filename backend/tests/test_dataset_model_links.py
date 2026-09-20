import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.routers import datasets
from app.schemas import DatasetModelLinkRequest


def test_relink_only_uses_dataset_version_relation(monkeypatch):
    primary = {
        "id": "primary", "source_id": "model", "target_id": "version",
        "relation_type": "trained_on", "status": "active", "revision": 1,
        "provenance": {"dataset_model_link_id": "first-link", "dataset_id": "dataset", "dataset_version_id": "version"},
    }
    member = {
        "id": "member", "source_id": "model", "target_id": "image",
        "relation_type": "trained_on", "status": "active", "revision": 1,
        "provenance": {"dataset_model_link_id": "old-link", "dataset_id": "dataset", "dataset_version_id": "version"},
    }
    rows = SimpleNamespace(sort=lambda *args: SimpleNamespace(to_list=AsyncMock(return_value=[primary, member])))
    relations = SimpleNamespace(find=lambda *args: rows, update_many=AsyncMock(), insert_many=AsyncMock())
    database = SimpleNamespace(
        dataset_versions=SimpleNamespace(find_one=AsyncMock(return_value={"id": "version", "dataset_id": "dataset"})),
        dataset_version_memberships=SimpleNamespace(find=lambda *args: SimpleNamespace(to_list=AsyncMock(return_value=[{"asset_id": "image"}]))),
        assets=SimpleNamespace(find_one=AsyncMock(return_value={"id": "model", "type": "model"})),
        relations=relations,
    )
    monkeypatch.setattr(datasets, "db", database)
    monkeypatch.setattr(datasets, "_get_dataset", AsyncMock(return_value={"id": "dataset"}))
    monkeypatch.setattr(datasets, "record_audit", AsyncMock())

    result = asyncio.run(datasets.add_dataset_model.__wrapped__(
        "dataset", DatasetModelLinkRequest(model_id="model", version_id="version", remark="updated"),
        SimpleNamespace(state=SimpleNamespace(request_id="test")), {"id": "user", "username": "admin"},
    ))

    assert result["created"] == 0
    assert result["member_relations"] == 0
    assert result["relation"]["provenance"]["dataset_model_link_id"] == "first-link"
    relations.insert_many.assert_not_awaited()
    update_query, update_document = relations.update_many.call_args.args
    assert update_query["provenance.dataset_version_id"] == "version"
    assert update_document["$set"]["provenance"]["dataset_model_link_id"] == "first-link"


def test_unlink_only_revokes_dataset_version_relation(monkeypatch):
    primary = {
        "id": "primary", "source_id": "model", "target_id": "version",
        "status": "active", "provenance": {"dataset_model_link_id": "new-link"},
    }
    relations = SimpleNamespace(find_one=AsyncMock(return_value=primary), update_many=AsyncMock(return_value=SimpleNamespace(modified_count=1)))
    database = SimpleNamespace(
        relations=relations,
        dataset_versions=SimpleNamespace(find_one=AsyncMock(return_value={"id": "version", "dataset_id": "dataset"})),
    )
    monkeypatch.setattr(datasets, "db", database)
    monkeypatch.setattr(datasets, "_get_dataset", AsyncMock(return_value={"id": "dataset"}))
    monkeypatch.setattr(datasets, "record_audit", AsyncMock())

    result = asyncio.run(datasets.remove_dataset_model.__wrapped__(
        "dataset", "primary", SimpleNamespace(state=SimpleNamespace(request_id="test")), {"id": "user"},
    ))

    assert result["revoked"] == 1
    query = relations.update_many.call_args.args[0]
    assert query == {"id": "primary", "status": "active"}
