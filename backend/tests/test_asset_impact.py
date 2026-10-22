import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.asset_impact import usage_impact
from app.errors import AppError
from app.routers import assets
from app.schemas import BatchAssetDeleteRequest, UploadInitRequest


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for row in self.rows:
            yield row

    def sort(self, *_args):
        return self

    async def to_list(self, length=None):
        return self.rows[:length] if length is not None else self.rows


def collection(rows):
    def matches(row, query):
        return all(
            any(matches(row, clause) for clause in value) if key == "$or" else
            row.get(key) in value["$in"] if isinstance(value, dict) and "$in" in value else
            row.get(key) == value
            for key, value in query.items()
        )

    def find(query, *_args):
        return Cursor([row for row in rows if matches(row, query)])

    return SimpleNamespace(find=find)


def test_usage_impact_shows_current_dataset_versions_and_models(monkeypatch):
    import app.asset_impact as impact

    database = SimpleNamespace(
        assets=collection([
            {"id": "image", "name": "样本.jpg", "type": "image", "archived_at": None},
            {"id": "model", "name": "检测模型", "type": "model", "archived_at": None},
        ]),
        dataset_memberships=collection([
            {"asset_id": "image", "dataset_id": "dataset"},
        ]),
        dataset_version_memberships=collection([
            {"asset_id": "image", "version_id": "version"},
        ]),
        dataset_versions=collection([
            {"id": "version", "dataset_id": "dataset", "version": "v1"},
        ]),
        datasets=collection([
            {"id": "dataset", "name": "烟火数据集", "deleted_at": None},
        ]),
        relations=collection([
            {"source_id": "model", "target_id": "version", "relation_type": "trained_on", "status": "active"},
        ]),
    )
    monkeypatch.setattr(impact, "db", database)

    result = asyncio.run(usage_impact(["image", "model"]))

    assert result["affected_count"] == 2
    image, model = result["items"]
    assert image["current_datasets"] == [{"id": "dataset", "name": "烟火数据集"}]
    assert image["historical_versions"][0]["version"] == "v1"
    assert image["models"] == [{"id": "model", "name": "检测模型"}]
    assert model["historical_versions"][0]["version"] == "v1"
    assert model["relation_count"] == 1


def test_usage_impact_marks_unreferenced_assets_and_truncation(monkeypatch):
    import app.asset_impact as impact

    ids = [f"asset-{index}" for index in range(101)]
    monkeypatch.setattr(impact, "db", SimpleNamespace(
        assets=collection([{"id": key, "name": key, "type": "image", "archived_at": None} for key in ids]),
        dataset_memberships=collection([]), dataset_version_memberships=collection([]),
        dataset_versions=collection([]), datasets=collection([]), relations=collection([]),
    ))

    result = asyncio.run(usage_impact(ids))

    assert result["affected_count"] == 0
    assert result["items"] == []
    assert result["details_truncated"] is False


def test_usage_impact_includes_direct_relations_and_limits_related_details(monkeypatch):
    import app.asset_impact as impact

    ids = [f"asset-{index}" for index in range(101)]
    monkeypatch.setattr(impact, "db", SimpleNamespace(
        assets=collection([{"id": key, "name": key, "type": "image", "archived_at": None}
                           for key in ids]),
        dataset_memberships=collection([]), dataset_version_memberships=collection([]),
        dataset_versions=collection([]), datasets=collection([]),
        relations=collection([{"source_id": key, "target_id": "annotation", "relation_type": "annotates",
                               "status": "active"} for key in ids]),
    ))

    result = asyncio.run(usage_impact(ids))

    assert result["affected_count"] == 101
    assert len(result["items"]) == 100
    assert result["details_truncated"] is True
    assert result["items"][0]["other_relation_count"] == 1


def test_usage_preview_resolves_selection(monkeypatch):
    async def resolve(*_args):
        return ["selected-asset"]

    async def preview(ids):
        return {"total": len(ids), "items": []}

    monkeypatch.setattr(assets, "resolve_selection_ids", resolve)
    monkeypatch.setattr(assets, "usage_impact", preview)
    result = asyncio.run(assets.preview_usage_impact(
        BatchAssetDeleteRequest(selection_id="selection"), {"id": "user"},
    ))
    assert result["total"] == 1


def test_overwrite_refuses_changed_target(monkeypatch):
    async def matches(*_args):
        return [{"id": "new-target"}]

    monkeypatch.setattr(assets, "matching_name_assets", matches)
    monkeypatch.setattr(assets, "ensure_action_access", lambda *_args: None)
    body = UploadInitRequest(
        filename="sample.jpg", size=10, mime_type="image/jpeg", asset_type="image",
        name_conflict="overwrite", expected_overwrite_asset_id="previewed-target",
    )
    with pytest.raises(AppError) as error:
        asyncio.run(assets.initialize_upload(body, {"id": "user"}))
    assert error.value.code == "OVERWRITE_TARGET_CHANGED"


def test_deleting_dataset_member_clears_links_and_recounts_version(monkeypatch):
    asset_store = collection([{"id": "image", "name": "样本.jpg"}])
    asset_store.update_many = AsyncMock(return_value=SimpleNamespace(modified_count=1))
    asset_store.distinct = AsyncMock(return_value=["image"])
    current_members = SimpleNamespace(
        distinct=AsyncMock(return_value=["dataset"]),
        delete_many=AsyncMock(return_value=SimpleNamespace(deleted_count=1)),
    )
    version_members = SimpleNamespace(
        distinct=AsyncMock(return_value=["version"]),
        delete_many=AsyncMock(return_value=SimpleNamespace(deleted_count=1)),
        find=lambda *_args: Cursor([{"asset_id": "remaining", "snapshot": {"size": 25}}]),
    )
    versions = SimpleNamespace(
        find=lambda *_args: Cursor([{"id": "version", "dataset_id": "dataset"}]),
        update_one=AsyncMock(),
    )
    database = SimpleNamespace(
        assets=asset_store, dataset_memberships=current_members,
        dataset_version_memberships=version_members, dataset_versions=versions,
        datasets=SimpleNamespace(update_many=AsyncMock()),
        relations=SimpleNamespace(delete_many=AsyncMock(
            return_value=SimpleNamespace(deleted_count=2),
        )),
    )
    monkeypatch.setattr(assets, "db", database)
    audit = AsyncMock()
    monkeypatch.setattr(assets, "record_audit", audit)
    result = asyncio.run(assets.batch_delete(
        BatchAssetDeleteRequest(asset_ids=["image"], confirm_linked=True),
        SimpleNamespace(state=SimpleNamespace(request_id="request")),
        {"id": "user", "username": "user"},
    ))

    assert result["succeeded"] == ["image"]
    assert result["failed"] == []
    current_members.delete_many.assert_awaited_once_with({"asset_id": {"$in": ["image"]}})
    version_members.delete_many.assert_awaited_once_with({"asset_id": {"$in": ["image"]}})
    database.relations.delete_many.assert_awaited_once()
    updated = versions.update_one.await_args.args[1]["$set"]
    assert updated["member_count"] == 1
    assert updated["total_size"] == 25
    expected = hashlib.sha256(json.dumps(
        [{"asset_id": "remaining", "snapshot": {"size": 25}}],
        ensure_ascii=False, sort_keys=True, default=str,
    ).encode()).hexdigest()
    assert updated["content_digest"] == expected
    assert audit.await_args.kwargs["changes"]["relations_deleted"] == 2


def test_deleting_linked_asset_requires_explicit_confirmation(monkeypatch):
    database = SimpleNamespace(
        dataset_memberships=SimpleNamespace(find_one=AsyncMock(return_value={"asset_id": "image"})),
    )
    monkeypatch.setattr(assets, "db", database)

    with pytest.raises(AppError) as error:
        asyncio.run(assets.batch_delete(
            BatchAssetDeleteRequest(asset_ids=["image"]),
            SimpleNamespace(state=SimpleNamespace(request_id="request")),
            {"id": "user"},
        ))
    assert error.value.code == "ASSET_RELATIONS_CONFIRM_REQUIRED"
