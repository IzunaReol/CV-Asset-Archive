from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.dataset_splits import allocation_preview, split_of
from app.errors import AppError
from app.routers import datasets
from app.schemas import DatasetAutoSplitRequest, DatasetSplitUpdate


def test_old_membership_is_unassigned_and_ratios_are_validated():
    assert split_of({}) == "unassigned"
    with pytest.raises(ValidationError):
        DatasetAutoSplitRequest(train=0, val=0, test=0)
    with pytest.raises(ValidationError):
        DatasetAutoSplitRequest(train=-1)


def test_auto_split_keeps_duplicate_content_together_and_inherits_existing():
    images = [
        {"id": "a", "sha256": "hash", "size": 10, "split": "train"},
        {"id": "b", "sha256": "hash", "size": 10, "split": "unassigned"},
        {"id": "c", "sha256": "other", "size": 10, "split": "unassigned"},
        {"id": "d", "sha256": "other", "size": 10, "split": "unassigned"},
    ]
    result = allocation_preview("dataset", images, {"train": 8, "val": 1, "test": 1})
    assert result["assignments"]["b"] == "train"
    assert result["assignments"]["c"] == result["assignments"]["d"]
    assert result["allocated_count"] == 3
    assert result == allocation_preview("dataset", images, {"train": 8, "val": 1, "test": 1})


def test_auto_split_skips_conflicting_existing_duplicate_group():
    images = [
        {"id": "a", "sha256": "hash", "size": 10, "split": "train"},
        {"id": "b", "sha256": "hash", "size": 10, "split": "test"},
        {"id": "c", "sha256": "hash", "size": 10, "split": "unassigned"},
    ]
    result = allocation_preview("dataset", images, {"train": 8, "val": 1, "test": 1})
    assert result["allocated_count"] == 0
    assert result["skipped"] == [{"asset_ids": ["c"], "assets": [{"id": "a", "name": "a", "split": "train"}, {"id": "b", "name": "b", "split": "test"}, {"id": "c", "name": "c", "split": "unassigned"}], "reason": "existing_split_conflict"}]


@pytest.mark.asyncio
async def test_manual_split_rejects_non_member_or_non_image(monkeypatch):
    monkeypatch.setattr(datasets, "_get_dataset", AsyncMock(return_value={"id": "dataset"}))
    monkeypatch.setattr(datasets, "_split_images", AsyncMock(return_value=[{"id": "image"}]))
    body = DatasetSplitUpdate(asset_ids=["video"], split="train")
    with pytest.raises(AppError) as error:
        await datasets.update_member_split.__wrapped__("dataset", body, None, {"id": "user"})
    assert error.value.code == "DATASET_SPLIT_ASSETS_INVALID"


@pytest.mark.asyncio
async def test_auto_split_requires_fresh_preview(monkeypatch):
    monkeypatch.setattr(datasets, "_get_dataset", AsyncMock(return_value={"id": "dataset"}))
    monkeypatch.setattr(datasets, "_auto_split_report", AsyncMock(return_value={"token": "a" * 64}))
    body = DatasetAutoSplitRequest(preview_token="b" * 64)
    with pytest.raises(AppError) as error:
        await datasets.apply_auto_split.__wrapped__("dataset", body, SimpleNamespace(), {"id": "user"})
    assert error.value.code == "DATASET_SPLIT_CHANGED"


class AsyncCursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *args):
        return self

    def __aiter__(self):
        self.iterator = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration:
            raise StopAsyncIteration


@pytest.mark.asyncio
async def test_restore_version_restores_image_split(monkeypatch):
    rows = [
        {"asset_id": "image", "snapshot": {"type": "image", "split": "test"}},
        {"asset_id": "old", "snapshot": {"type": "image"}},
        {"asset_id": "annotation", "snapshot": {"type": "annotation"}},
    ]
    memberships = SimpleNamespace(delete_many=AsyncMock(), insert_many=AsyncMock())
    monkeypatch.setattr(datasets, "db", SimpleNamespace(
        dataset_memberships=memberships,
        dataset_version_memberships=SimpleNamespace(find=lambda *args: AsyncCursor(rows)),
        datasets=SimpleNamespace(find_one=AsyncMock(return_value={"id": "dataset"}), update_one=AsyncMock()),
    ))
    monkeypatch.setattr(datasets, "sync_annotation_memberships", AsyncMock())
    await datasets._restore_memberships_from_version("dataset", "version", "user")
    written = memberships.insert_many.await_args.args[0]
    assert [(item["asset_id"], item["split"]) for item in written] == [
        ("image", "test"), ("old", "unassigned")
    ]


def test_split_change_changes_version_digest():
    asset = {"id": "image", "type": "image", "name": "one.jpg", "size": 10}
    before = {"asset_id": "image", "snapshot": datasets._asset_snapshot({**asset, "_dataset_split": "train"})}
    after = {"asset_id": "image", "snapshot": datasets._asset_snapshot({**asset, "_dataset_split": "test"})}
    assert datasets._content_digest([before]) != datasets._content_digest([after])


def test_custom_allocation_and_classification_defaults():
    rule, labels = datasets._classification({"id": "old"})
    assert rule == "standard" and labels["train"] == "训练集"
    rule, labels = datasets._classification({"classification_rule": "custom", "custom_categories": {"custom_a": "阶段一", "custom_b": "阶段二"}})
    assert rule == "custom" and labels["unassigned"] == "未划分"
    result = allocation_preview("dataset", [{"id": "a", "split": "unassigned"}], {"custom_a": 1, "custom_b": 0})
    assert result["assignments"] == {"a": "custom_a"}
    assert datasets._classification({"classification_rule": "none"}) == ("none", {})


def test_category_name_must_be_unique():
    with pytest.raises(AppError) as error:
        datasets._validate_category_name(" 阶段一 ", {"custom_a": "阶段一"})
    assert error.value.code == "DATASET_CATEGORY_NAME_EXISTS"
    assert datasets._validate_category_name(" 阶段二 ", {"custom_a": "阶段一"}) == "阶段二"


@pytest.mark.asyncio
async def test_custom_category_delete_resets_only_its_members(monkeypatch):
    monkeypatch.setattr(datasets, "_get_dataset", AsyncMock(return_value={"id": "dataset", "classification_rule": "custom", "custom_categories": {"custom_a": "阶段一", "custom_b": "阶段二"}}))
    memberships = SimpleNamespace(update_many=AsyncMock(return_value=SimpleNamespace(modified_count=2)))
    dataset_collection = SimpleNamespace(update_one=AsyncMock())
    monkeypatch.setattr(datasets, "db", SimpleNamespace(dataset_memberships=memberships, datasets=dataset_collection))
    monkeypatch.setattr(datasets, "record_audit", AsyncMock())
    result = await datasets.delete_category.__wrapped__("dataset", "custom_a", SimpleNamespace(state=SimpleNamespace(request_id="req")), {"id": "user"})
    assert result == {"reset_count": 2, "categories": {"custom_b": "阶段二"}}
    assert memberships.update_many.await_args.args[0] == {"dataset_id": "dataset", "split": "custom_a"}


@pytest.mark.asyncio
async def test_custom_auto_split_rejects_stale_category_ratios(monkeypatch):
    monkeypatch.setattr(datasets, "_get_dataset", AsyncMock(return_value={"id": "dataset", "classification_rule": "custom", "custom_categories": {"custom_a": "阶段一"}}))
    monkeypatch.setattr(datasets, "_split_images", AsyncMock(return_value=[]))
    with pytest.raises(AppError) as error:
        await datasets._auto_split_report("dataset", DatasetAutoSplitRequest(ratios={"custom_b": 1}))
    assert error.value.code == "DATASET_SPLIT_RATIOS_INVALID"


@pytest.mark.asyncio
async def test_member_list_accepts_multiple_split_filters(monkeypatch):
    class Cursor:
        def __init__(self, rows):
            self.rows = rows

        async def to_list(self, length):
            return self.rows

    aggregate = AsyncMock(side_effect=[Cursor([{"count": 2}]), Cursor([{"id": "train-image"}, {"id": "test-image"}])])
    monkeypatch.setattr(datasets, "_get_dataset", AsyncMock(return_value={"id": "dataset"}))
    monkeypatch.setattr(datasets, "db", SimpleNamespace(dataset_memberships=SimpleNamespace(aggregate=aggregate)))
    result = await datasets.list_members("dataset", {}, page=1, page_size=50, q="", asset_type=[], tag=[], match="all", no_tags=False, ids_only=True, split=["train", "test"])
    assert result["total"] == 2
    assert [item["id"] for item in result["items"]] == ["train-image", "test-image"]
    first_pipeline = aggregate.await_args_list[0].args[0]
    assert first_pipeline[1] == {"$match": {"split": {"$in": ["test", "train"]}}}
    assert {"type": "image", "dataset_split": {"$in": ["test", "train"]}} in first_pipeline[6]["$match"]["$and"]

    with pytest.raises(AppError) as error:
        await datasets.list_members("dataset", {}, page=1, page_size=50, q="", asset_type=[], tag=[], match="all", no_tags=False, ids_only=True, split=["invalid"])
    assert error.value.code == "INVALID_SPLIT_FILTER"
