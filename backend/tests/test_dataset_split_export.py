from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.errors import AppError
from app.routers import datasets
from app.schemas import DatasetExportRequest


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, length=None):
        return self.rows


def test_export_request_requires_a_valid_selection():
    with pytest.raises(ValidationError):
        DatasetExportRequest(export_type="current")
    with pytest.raises(ValidationError):
        DatasetExportRequest(export_type="categories")
    with pytest.raises(ValidationError):
        DatasetExportRequest(export_type="all", asset_ids=["image"])
    assert DatasetExportRequest(export_type="categories", splits=["train", "train"]).splits == ["train"]


def test_export_category_folders_use_display_names_and_avoid_collisions():
    labels = {"custom_a": "正常", "custom_b": "抽烟", "custom_c": "正常/异常", "custom_d": "正常:异常"}
    folders = datasets._export_category_folders(labels, set(labels))
    assert folders == {"custom_a": "正常", "custom_b": "抽烟", "custom_c": "正常_异常", "custom_d": "正常_异常 (2)"}


@pytest.mark.asyncio
async def test_split_export_freezes_entries_and_names_from_current_version(monkeypatch):
    memberships = [
        {"asset_id": "image", "split": "train"},
        {"asset_id": "annotation"},
        {"asset_id": "video"},
    ]
    assets = [
        {"id": "image", "name": "one.jpg", "type": "image"},
        {"id": "annotation", "name": "one.txt", "type": "annotation"},
        {"id": "video", "name": "sample.mp4", "type": "video"},
    ]
    jobs = SimpleNamespace(insert_one=AsyncMock())
    database = SimpleNamespace(
        dataset_memberships=SimpleNamespace(find=lambda *args: Cursor(memberships)),
        assets=SimpleNamespace(find=lambda *args: Cursor(assets)),
        relations=SimpleNamespace(find=lambda *args: Cursor([{"source_id": "annotation", "target_id": "image"}])),
        jobs=jobs,
    )
    monkeypatch.setattr(datasets, "db", database)
    monkeypatch.setattr(datasets, "_get_dataset", AsyncMock(return_value={"id": "dataset", "name": "烟火", "current_version": "v2"}))
    monkeypatch.setattr(datasets, "record_audit", AsyncMock())
    monkeypatch.setattr(datasets.celery_client, "send_task", MagicMock())
    request = SimpleNamespace(state=SimpleNamespace(request_id="request"))
    user = {"id": "user", "username": "user"}

    await datasets.export_dataset.__wrapped__("dataset", DatasetExportRequest(export_type="train"), request, user)
    train_job = jobs.insert_one.await_args.args[0]
    assert train_job["name"] == "烟火 v2 训练集"
    assert {(item["asset_id"], item["folder"]) for item in train_job["input"]["entries"]} == {("image", "训练集")}

    await datasets.export_dataset.__wrapped__("dataset", DatasetExportRequest(export_type="train", include_annotations=True), request, user)
    train_with_annotations = jobs.insert_one.await_args.args[0]
    assert {(item["asset_id"], item["folder"]) for item in train_with_annotations["input"]["entries"]} == {("image", "训练集"), ("annotation", "训练集")}

    await datasets.export_dataset.__wrapped__("dataset", DatasetExportRequest(), request, user)
    all_job = jobs.insert_one.await_args.args[0]
    assert all_job["name"] == "烟火 v2 全部导出"
    assert {(item["asset_id"], item["folder"]) for item in all_job["input"]["entries"]} == {("image", ""), ("video", "")}

    await datasets.export_dataset.__wrapped__("dataset", DatasetExportRequest(include_annotations=True), request, user)
    all_with_annotations = jobs.insert_one.await_args.args[0]
    assert {(item["asset_id"], item["folder"]) for item in all_with_annotations["input"]["entries"]} == {("image", ""), ("annotation", ""), ("video", "")}

    await datasets.export_dataset.__wrapped__("dataset", DatasetExportRequest(export_type="current", asset_ids=["image"]), request, user)
    current_job = jobs.insert_one.await_args.args[0]
    assert current_job["name"] == "烟火 v2 导出当前"
    assert {item["asset_id"] for item in current_job["input"]["entries"]} == {"image"}

    await datasets.export_dataset.__wrapped__("dataset", DatasetExportRequest(export_type="current", asset_ids=["image"], include_annotations=True), request, user)
    current_with_annotations = jobs.insert_one.await_args.args[0]
    assert {(item["asset_id"], item["folder"]) for item in current_with_annotations["input"]["entries"]} == {("image", ""), ("annotation", "")}

    await datasets.export_dataset.__wrapped__("dataset", DatasetExportRequest(export_type="categories", splits=["train", "val"]), request, user)
    selected_job = jobs.insert_one.await_args.args[0]
    assert selected_job["name"] == "烟火 v2 指定分类（训练集、验证集）"
    assert {item["asset_id"] for item in selected_job["input"]["entries"]} == {"image"}

    await datasets.export_dataset.__wrapped__("dataset", DatasetExportRequest(export_type="categories", splits=["train", "val"], include_annotations=True), request, user)
    categories_with_annotations = jobs.insert_one.await_args.args[0]
    assert {(item["asset_id"], item["folder"]) for item in categories_with_annotations["input"]["entries"]} == {("image", "训练集"), ("annotation", "训练集")}

    with pytest.raises(AppError) as empty:
        await datasets.export_dataset.__wrapped__("dataset", DatasetExportRequest(export_type="categories", splits=["unassigned"]), request, user)
    assert empty.value.code == "DATASET_EMPTY"


@pytest.mark.asyncio
async def test_split_export_blocks_cross_split_legacy_annotation(monkeypatch):
    memberships = [{"asset_id": "a", "split": "train"}, {"asset_id": "b", "split": "test"}, {"asset_id": "ann"}]
    assets = [{"id": "a", "name": "a.jpg", "type": "image"}, {"id": "b", "name": "b.jpg", "type": "image"}, {"id": "ann", "name": "ann.json", "type": "annotation"}]
    jobs = SimpleNamespace(insert_one=AsyncMock())
    monkeypatch.setattr(datasets, "db", SimpleNamespace(
        dataset_memberships=SimpleNamespace(find=lambda *args: Cursor(memberships)),
        assets=SimpleNamespace(find=lambda *args: Cursor(assets)),
        relations=SimpleNamespace(find=lambda *args: Cursor([{"source_id": "ann", "target_id": "a"}, {"source_id": "ann", "target_id": "b"}])),
        jobs=jobs,
    ))
    monkeypatch.setattr(datasets, "_get_dataset", AsyncMock(return_value={"name": "数据集"}))
    monkeypatch.setattr(datasets, "record_audit", AsyncMock())
    monkeypatch.setattr(datasets.celery_client, "send_task", MagicMock())
    await datasets.export_dataset.__wrapped__(
        "dataset", DatasetExportRequest(export_type="train"),
        SimpleNamespace(state=SimpleNamespace(request_id="request")), {"id": "user"},
    )
    assert [item["asset_id"] for item in jobs.insert_one.await_args.args[0]["input"]["entries"]] == ["a"]
    with pytest.raises(AppError) as error:
        await datasets.export_dataset.__wrapped__("dataset", DatasetExportRequest(export_type="train", include_annotations=True), None, None)
    assert error.value.code == "DATASET_EXPORT_SHARED_ANNOTATION"
    with pytest.raises(AppError) as current_error:
        await datasets.export_dataset.__wrapped__("dataset", DatasetExportRequest(export_type="current", asset_ids=["a"], include_annotations=True), None, None)
    assert current_error.value.code == "DATASET_EXPORT_SHARED_ANNOTATION"
    with pytest.raises(AppError) as category_error:
        await datasets.export_dataset.__wrapped__("dataset", DatasetExportRequest(export_type="categories", splits=["train", "test"], include_annotations=True), None, None)
    assert category_error.value.code == "DATASET_EXPORT_SHARED_ANNOTATION"
