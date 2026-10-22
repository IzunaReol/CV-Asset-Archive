import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.routers import datasets
from app.schemas import DatasetModelLinkRequest
from app.schemas import DatasetModelRemarkUpdate
from app.errors import AppError
import pytest


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


def test_update_model_link_changes_remark_only(monkeypatch):
    relation = {
        "id": "primary", "source_id": "model", "target_id": "version",
        "relation_type": "trained_on", "status": "active",
        "provenance": {"remark": "旧备注", "dataset_id": "dataset"},
    }
    relations = SimpleNamespace(
        find_one=AsyncMock(return_value=relation),
        update_one=AsyncMock(return_value=SimpleNamespace(matched_count=1)),
    )
    monkeypatch.setattr(datasets, "db", SimpleNamespace(
        relations=relations,
        dataset_versions=SimpleNamespace(find_one=AsyncMock(return_value={"id": "version", "dataset_id": "dataset"})),
    ))
    monkeypatch.setattr(datasets, "_get_dataset", AsyncMock(return_value={"id": "dataset"}))
    audit = AsyncMock()
    monkeypatch.setattr(datasets, "record_audit", audit)

    result = asyncio.run(datasets.update_dataset_model_remark.__wrapped__(
        "dataset", "primary", DatasetModelRemarkUpdate(remark=" 新备注 "),
        SimpleNamespace(state=SimpleNamespace(request_id="test")), {"id": "user"},
    ))

    assert result["relation"]["provenance"]["remark"] == "新备注"
    assert relations.update_one.call_args.args[1] == {"$set": {"provenance.remark": "新备注"}}
    assert relations.update_one.call_args.args[0]["status"] == "active"
    assert audit.call_args.kwargs["action"] == "dataset.model_link_remark_updated"


def test_update_model_link_rejects_other_dataset(monkeypatch):
    relation = {"id": "primary", "target_id": "version", "relation_type": "trained_on", "status": "active"}
    relations = SimpleNamespace(find_one=AsyncMock(return_value=relation), update_one=AsyncMock())
    monkeypatch.setattr(datasets, "db", SimpleNamespace(
        relations=relations,
        dataset_versions=SimpleNamespace(find_one=AsyncMock(return_value=None)),
    ))
    monkeypatch.setattr(datasets, "_get_dataset", AsyncMock(return_value={"id": "other"}))
    with pytest.raises(AppError) as error:
        asyncio.run(datasets.update_dataset_model_remark.__wrapped__(
            "other", "primary", DatasetModelRemarkUpdate(remark="新备注"),
            SimpleNamespace(state=SimpleNamespace(request_id="test")), {"id": "user"},
        ))
    assert error.value.status_code == 400
    relations.update_one.assert_not_awaited()


def test_model_remark_request_rejects_relation_fields():
    with pytest.raises(ValueError):
        DatasetModelRemarkUpdate(remark="ok", model_id="another", version_id="another")


@pytest.mark.asyncio
async def test_list_models_includes_only_configured_parameter_values(monkeypatch):
    relation = {
        "id": "relation-1", "source_id": "model-1", "target_id": "version-1",
        "relation_type": "trained_on", "status": "active",
    }
    def cursor(items):
        return SimpleNamespace(to_list=AsyncMock(return_value=items), sort=lambda *args: cursor(items))

    database = SimpleNamespace(
        dataset_versions=SimpleNamespace(
            distinct=AsyncMock(return_value=["version-1"]),
            find=lambda *args: cursor([{"id": "version-1", "version": "v1"}]),
        ),
        relations=SimpleNamespace(find=lambda *args: cursor([relation])),
        assets=SimpleNamespace(find=lambda *args: cursor([{
            "id": "model-1", "type": "model", "name": "检测模型",
            "metric_values": {"accuracy": "0.95", "empty": "", "removed": "0.8"},
        }])),
        metric_definitions=SimpleNamespace(find=lambda *args: cursor([{
            "id": "accuracy", "name": "准确率", "category": "图像分类",
        }])),
    )
    monkeypatch.setattr(datasets, "db", database)
    monkeypatch.setattr(datasets, "_get_dataset", AsyncMock(return_value={"id": "dataset-1"}))

    result = await datasets.list_dataset_models("dataset-1", {"id": "user-1"})

    assert result["items"][0]["configured_parameters"] == [{
        "id": "accuracy", "name": "准确率", "category": "图像分类", "value": "0.95",
    }]
