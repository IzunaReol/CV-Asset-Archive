from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError

from app.bootstrap import DEFAULT_METRICS, DEFAULT_METRIC_CATEGORIES, ensure_default_metric_categories, ensure_default_metrics
from app import bootstrap
from app.dependencies import require_action, require_menu
from app.errors import AppError
from app.routers import parameters
from app.schemas import MetricCategoryCreate, MetricDefinitionWrite


def test_defaults_and_validation():
    assert len(DEFAULT_METRICS) == 16
    assert {item[2] for item in DEFAULT_METRICS} == {"图像分类", "目标检测", "语义分割", "实例分割", "OCR", "姿态和关键点"}
    assert {item[0] for item in DEFAULT_METRICS} == {
        "accuracy", "precision", "recall", "f1", "map", "iou", "ap", "pixel_accuracy",
        "miou", "dice", "instance_map", "instance_iou", "cer", "wer", "pck", "oks",
    }
    assert len({(item[2], item[1]) for item in DEFAULT_METRICS}) == 16
    assert MetricDefinitionWrite(name="mIoU", category="语义分割", description="像素级交并比").category == "语义分割"
    for payload in [
        {"name": " ", "category": "图像分类", "description": "有效描述"},
        {"name": "新指标", "category": " ", "description": "有效描述"},
        {"name": "新指标", "category": "图像分类", "description": " "},
        {"name": "新指标", "category": "图像分类", "description": "有效描述", "score": 0.9},
    ]:
        with pytest.raises(ValidationError):
            MetricDefinitionWrite(**payload)


@pytest.mark.asyncio
async def test_default_metrics_are_inserted_without_overwriting_existing_edits(monkeypatch):
    collection = SimpleNamespace(update_one=AsyncMock())
    categories = SimpleNamespace(update_one=AsyncMock())
    monkeypatch.setattr(bootstrap, "db", SimpleNamespace(metric_definitions=collection, metric_categories=categories))
    await ensure_default_metric_categories()
    await ensure_default_metrics()
    assert len(DEFAULT_METRIC_CATEGORIES) == 6
    assert categories.update_one.await_count == 6
    for call in categories.update_one.await_args_list:
        assert set(call.args[1]) == {"$setOnInsert"}
        assert call.kwargs["upsert"] is True
    assert collection.update_one.await_count == 16
    for call in collection.update_one.await_args_list:
        assert set(call.args[1]) == {"$setOnInsert"}
        assert call.kwargs["upsert"] is True


@pytest.mark.asyncio
async def test_metric_permissions():
    await require_menu("parameters")({"roles": ["admin"]})
    with pytest.raises(AppError):
        await require_menu("parameters")({"roles": ["viewer"]})
    reader = {"roles": ["custom"], "menu_permissions": ["parameters"], "action_permissions": []}
    await require_menu("parameters")(reader)
    with pytest.raises(AppError):
        await require_action("parameter_manage")(reader)
    writer = {**reader, "action_permissions": ["parameter_manage"]}
    await require_action("parameter_manage")(writer)


@pytest.mark.asyncio
async def test_create_update_delete_metric(monkeypatch):
    row = {"id": "metric-1", "name": "准确率", "category": "图像分类", "description": "描述", "built_in": False}
    collection = SimpleNamespace(
        insert_one=AsyncMock(), update_one=AsyncMock(return_value=SimpleNamespace(matched_count=1)),
        find_one=AsyncMock(return_value=row), delete_one=AsyncMock(return_value=SimpleNamespace(deleted_count=1)),
    )
    assets = SimpleNamespace(update_many=AsyncMock())
    monkeypatch.setattr(parameters, "db", SimpleNamespace(metric_definitions=collection, metric_categories=SimpleNamespace(find_one=AsyncMock(return_value={"name": "图像分类"})), assets=assets))
    monkeypatch.setattr(parameters, "record_audit", AsyncMock())
    monkeypatch.setattr(parameters, "new_id", lambda: "metric-1")
    request = SimpleNamespace(state=SimpleNamespace(request_id="request-1"))
    user = {"id": "admin"}
    body = MetricDefinitionWrite(name=" 准确率 ", category="图像分类", description=" 描述 ")

    created = await parameters.create_metric(body, request, user)
    assert created["name"] == "准确率"
    assert created["built_in"] is False
    updated = await parameters.update_metric("metric-1", body, request, user)
    assert updated["id"] == "metric-1"
    assert collection.update_one.call_args.args[1]["$set"]["description"] == "描述"
    await parameters.delete_metric("metric-1", request, user)
    collection.delete_one.assert_awaited_once()
    assets.update_many.assert_awaited_once()


@pytest.mark.asyncio
async def test_builtin_protected_and_duplicate_rejected(monkeypatch):
    collection = SimpleNamespace(
        insert_one=AsyncMock(side_effect=DuplicateKeyError("duplicate")),
        find_one=AsyncMock(return_value={"id": "metric-accuracy", "name": "准确率", "built_in": True}),
        delete_one=AsyncMock(),
    )
    monkeypatch.setattr(parameters, "db", SimpleNamespace(metric_definitions=collection, metric_categories=SimpleNamespace(find_one=AsyncMock(return_value={"name": "图像分类"}))))
    request = SimpleNamespace(state=SimpleNamespace(request_id="request-1"))
    user = {"id": "admin"}
    body = MetricDefinitionWrite(name="准确率", category="图像分类", description="描述")
    with pytest.raises(AppError) as duplicate:
        await parameters.create_metric(body, request, user)
    assert duplicate.value.status_code == 409
    with pytest.raises(AppError) as protected:
        await parameters.delete_metric("metric-accuracy", request, user)
    assert protected.value.code == "BUILT_IN_METRIC_PROTECTED"
    collection.delete_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_category_creation_and_metric_category_validation(monkeypatch):
    collection = SimpleNamespace(insert_one=AsyncMock())
    categories = SimpleNamespace(insert_one=AsyncMock(), find_one=AsyncMock(return_value=None))
    audit = AsyncMock()
    monkeypatch.setattr(parameters, "db", SimpleNamespace(metric_definitions=collection, metric_categories=categories))
    monkeypatch.setattr(parameters, "record_audit", audit)
    request = SimpleNamespace(state=SimpleNamespace(request_id="request-1"))
    user = {"id": "admin"}

    category = await parameters.create_category(MetricCategoryCreate(name=" 音频识别 "), request, user)
    assert category["name"] == "音频识别"
    assert category["built_in"] is False
    with pytest.raises(AppError) as missing:
        await parameters.create_metric(
            MetricDefinitionWrite(name="准确率", category="音频识别", description="描述"), request, user,
        )
    assert missing.value.code == "METRIC_CATEGORY_NOT_FOUND"
    collection.insert_one.assert_not_awaited()
    categories.find_one.return_value = {"name": "音频识别"}
    await parameters.create_metric(
        MetricDefinitionWrite(name="准确率", category="音频识别", description="描述"), request, user,
    )
    collection.insert_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_category_is_rejected(monkeypatch):
    collection = SimpleNamespace(insert_one=AsyncMock(side_effect=DuplicateKeyError("duplicate")))
    monkeypatch.setattr(parameters, "db", SimpleNamespace(metric_categories=collection))
    with pytest.raises(AppError) as duplicate:
        await parameters.create_category(
            MetricCategoryCreate(name="OCR"), SimpleNamespace(state=SimpleNamespace(request_id="request-1")),
            {"id": "admin"},
        )
    assert duplicate.value.code == "METRIC_CATEGORY_EXISTS"


@pytest.mark.asyncio
async def test_delete_category_protects_builtin_and_in_use(monkeypatch):
    request = SimpleNamespace(state=SimpleNamespace(request_id="request-1"))
    user = {"id": "admin"}
    category = {"id": "custom-category", "name": "音频识别", "built_in": False}
    categories = SimpleNamespace(
        find_one=AsyncMock(return_value={**category, "built_in": True}),
        delete_one=AsyncMock(return_value=SimpleNamespace(deleted_count=1)),
    )
    metrics = SimpleNamespace(count_documents=AsyncMock(return_value=1))
    audit = AsyncMock()
    monkeypatch.setattr(parameters, "db", SimpleNamespace(metric_categories=categories, metric_definitions=metrics))
    monkeypatch.setattr(parameters, "record_audit", audit)

    with pytest.raises(AppError) as builtin:
        await parameters.delete_category("custom-category", request, user)
    assert builtin.value.code == "BUILT_IN_CATEGORY_PROTECTED"
    categories.find_one.return_value = category
    with pytest.raises(AppError) as in_use:
        await parameters.delete_category("custom-category", request, user)
    assert in_use.value.code == "METRIC_CATEGORY_IN_USE"
    categories.delete_one.assert_not_awaited()
    metrics.count_documents.return_value = 0
    await parameters.delete_category("custom-category", request, user)
    categories.delete_one.assert_awaited_once_with({"id": "custom-category", "built_in": False})
    assert audit.call_args.kwargs["action"] == "metric_category.deleted"


@pytest.mark.asyncio
async def test_rename_custom_category_updates_its_metrics(monkeypatch):
    category = {"id": "custom-category", "name": "音频识别", "built_in": False}
    categories = SimpleNamespace(
        find_one=AsyncMock(side_effect=[category, {**category, "name": "语音识别"}]),
        update_one=AsyncMock(return_value=SimpleNamespace(matched_count=1)),
    )
    metrics = SimpleNamespace(update_many=AsyncMock())
    audit = AsyncMock()
    monkeypatch.setattr(parameters, "db", SimpleNamespace(metric_categories=categories, metric_definitions=metrics))
    monkeypatch.setattr(parameters, "record_audit", audit)
    result = await parameters.update_category(
        "custom-category", MetricCategoryCreate(name=" 语音识别 "),
        SimpleNamespace(state=SimpleNamespace(request_id="request-1")), {"id": "admin"},
    )
    assert result["name"] == "语音识别"
    metrics.update_many.assert_awaited_once()
    assert metrics.update_many.call_args.args[0] == {"category": "音频识别"}
    assert metrics.update_many.call_args.args[1]["$set"]["category"] == "语音识别"
    assert audit.call_args.kwargs["action"] == "metric_category.updated"


@pytest.mark.asyncio
async def test_rename_category_protects_builtin_and_duplicate(monkeypatch):
    categories = SimpleNamespace(
        find_one=AsyncMock(return_value={"id": "category-1", "name": "图像分类", "built_in": True}),
        update_one=AsyncMock(side_effect=DuplicateKeyError("duplicate")),
    )
    metrics = SimpleNamespace(update_many=AsyncMock())
    monkeypatch.setattr(parameters, "db", SimpleNamespace(metric_categories=categories, metric_definitions=metrics))
    request = SimpleNamespace(state=SimpleNamespace(request_id="request-1"))
    with pytest.raises(AppError) as protected:
        await parameters.update_category("category-1", MetricCategoryCreate(name="新分类"), request, {"id": "admin"})
    assert protected.value.code == "BUILT_IN_CATEGORY_PROTECTED"
    categories.find_one.return_value = {"id": "category-1", "name": "旧分类", "built_in": False}
    with pytest.raises(AppError) as duplicate:
        await parameters.update_category("category-1", MetricCategoryCreate(name="新分类"), request, {"id": "admin"})
    assert duplicate.value.code == "METRIC_CATEGORY_EXISTS"
    metrics.update_many.assert_not_awaited()
