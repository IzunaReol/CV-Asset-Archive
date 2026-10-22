from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.dependencies import require_menu
from app.errors import AppError
from app.routers import projects


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_args):
        return self

    def limit(self, *_args):
        return self

    async def to_list(self, length=None):
        return self.rows if length is None else self.rows[:length]


@pytest.mark.asyncio
async def test_project_overview_groups_current_members_and_deduplicates_models(monkeypatch):
    datasets = [
        {"id": "d1", "name": "数据集一", "projects": ["A", "B"], "current_version": "v1"},
        {"id": "d2", "name": "旧数据集", "projects": ["A"]},
    ]
    model = {"id": "m1", "name": "模型一", "remark": "基线模型", "tags": {"project": ["A"]}}
    file = {"id": "f1", "name": "图片一", "type": "image", "tags": {"project": ["A", "B"]}}
    assets = SimpleNamespace(
        find=MagicMock(side_effect=lambda query, *_args: Cursor(
            [model] if query.get("type") == "model" else [file]
        )),
        count_documents=AsyncMock(return_value=1),
        aggregate=AsyncMock(return_value=Cursor([{"_id": {"type": "image"}, "count": 1}])),
    )
    database = SimpleNamespace(
        tag_definitions=SimpleNamespace(find_one=AsyncMock(return_value={"values": ["A", "B"]})),
        datasets=SimpleNamespace(find=MagicMock(return_value=Cursor(datasets))),
        dataset_memberships=SimpleNamespace(aggregate=AsyncMock(return_value=Cursor([
            {"_id": {"dataset_id": "d1", "type": "image"}, "count": 2},
            {"_id": {"dataset_id": "d1", "type": "annotation"}, "count": 1},
            {"_id": {"dataset_id": "d2", "type": "video"}, "count": 1},
        ]))),
        dataset_versions=SimpleNamespace(find=MagicMock(return_value=Cursor([
            {"id": "v1", "dataset_id": "d1", "version": "v1"},
        ]))),
        relations=SimpleNamespace(find=MagicMock(return_value=Cursor([
            {"source_id": "m1", "target_id": "v1"},
        ]))),
        assets=assets,
    )
    monkeypatch.setattr(projects, "db", database)
    result = await projects.project_overview({"roles": ["admin"]}, projects=["A", "B"])

    assert result["summary"] == {"project_count": 2, "dataset_count": 2, "model_count": 1, "file_count": 1}
    a, b = result["projects"]
    assert a["dataset_count"] == 2
    assert [item["name"] for item in a["datasets"]] == ["数据集一", "旧数据集"]
    assert a["dataset_counts"]["image"] == 2
    assert a["dataset_counts"]["video"] == 1
    assert b["dataset_count"] == 1
    assert b["dataset_counts"]["image"] == 2
    database.dataset_memberships.aggregate.assert_awaited_once()
    assets.aggregate.assert_awaited()
    assert a["models"][0]["sources"] == ["数据集关联", "项目标签"]
    assert b["models"][0]["sources"] == ["数据集关联"]
    assert a["file_count"] == b["file_count"] == 1


@pytest.mark.asyncio
async def test_project_models_show_configured_parameters_and_sort_by_latest_linked_version(monkeypatch):
    models = [
        {"id": "old", "name": "A 模型", "tags": {"project": ["A"]}, "metric_values": {"accuracy": "0.91", "empty": "", "missing": "0.5"}},
        {"id": "new", "name": "Z 模型", "tags": {"project": ["A"]}, "metric_values": {"accuracy": "0.98"}},
        {"id": "direct", "name": "直接标注", "tags": {"project": ["A"]}},
    ]
    database = SimpleNamespace(
        tag_definitions=SimpleNamespace(find_one=AsyncMock(return_value={"values": ["A"]})),
        datasets=SimpleNamespace(find=MagicMock(return_value=Cursor([{"id": "d1", "name": "数据集", "projects": ["A"]}]))),
        dataset_memberships=SimpleNamespace(aggregate=AsyncMock(return_value=Cursor([]))),
        dataset_versions=SimpleNamespace(find=MagicMock(return_value=Cursor([
            {"id": "v1", "dataset_id": "d1", "version": "v1", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "v2", "dataset_id": "d1", "version": "v2", "created_at": "2026-03-01T00:00:00Z"},
            {"id": "v3", "dataset_id": "d1", "version": "v3", "created_at": "2026-02-01T00:00:00Z"},
        ]))),
        relations=SimpleNamespace(find=MagicMock(return_value=Cursor([
            {"source_id": "new", "target_id": "v1"},
            {"source_id": "new", "target_id": "v2"},
            {"source_id": "old", "target_id": "v3"},
        ]))),
        assets=SimpleNamespace(
            find=MagicMock(side_effect=lambda query, *_args: Cursor(models if query.get("type") == "model" else [])),
            count_documents=AsyncMock(return_value=0),
            aggregate=AsyncMock(return_value=Cursor([])),
        ),
        metric_definitions=SimpleNamespace(find=MagicMock(return_value=Cursor([
            {"id": "accuracy", "name": "准确率", "category": "图像分类"},
            {"id": "empty", "name": "空值", "category": "图像分类"},
        ]))),
    )
    monkeypatch.setattr(projects, "db", database)
    result = await projects.project_overview({"roles": ["admin"]}, projects=["A"])

    project_models = result["projects"][0]["models"]
    assert [item["id"] for item in project_models] == ["new", "old", "direct"]
    assert project_models[0]["configured_parameters"] == [
        {"id": "accuracy", "name": "准确率", "category": "图像分类", "value": "0.98"}
    ]
    assert project_models[1]["configured_parameters"] == [
        {"id": "accuracy", "name": "准确率", "category": "图像分类", "value": "0.91"}
    ]
    assert project_models[2]["configured_parameters"] == []


@pytest.mark.asyncio
async def test_project_overview_hides_data_without_source_menu_permissions(monkeypatch):
    dataset_find = MagicMock()
    asset_find = MagicMock()
    monkeypatch.setattr(projects, "db", SimpleNamespace(
        tag_definitions=SimpleNamespace(find_one=AsyncMock(return_value={"values": ["A"]})),
        datasets=SimpleNamespace(find=dataset_find),
        assets=SimpleNamespace(find=asset_find),
    ))
    result = await projects.project_overview({"roles": ["custom"], "menu_permissions": ["project_overview"]}, projects=["A"])
    assert result["projects"][0]["datasets"] == []
    assert result["projects"][0]["models"] == []
    dataset_find.assert_not_called()
    asset_find.assert_not_called()


@pytest.mark.asyncio
async def test_project_overview_empty_projects_and_invalid_filter(monkeypatch):
    dataset_find = MagicMock()
    monkeypatch.setattr(projects, "db", SimpleNamespace(
        tag_definitions=SimpleNamespace(find_one=AsyncMock(return_value={"values": []})),
        datasets=SimpleNamespace(find=dataset_find),
    ))
    result = await projects.project_overview({"roles": ["admin"]}, projects=[])
    assert result["summary"] == {"project_count": 0, "dataset_count": 0, "model_count": 0, "file_count": 0}
    assert result["projects"] == []
    dataset_find.assert_not_called()
    with pytest.raises(AppError) as error:
        await projects.project_overview({"roles": ["admin"]}, projects=["不存在的项目"])
    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_project_overview_requires_its_own_menu():
    dependency = require_menu("project_overview")
    with pytest.raises(AppError) as error:
        await dependency({"roles": ["custom"], "menu_permissions": ["overview"]})
    assert error.value.status_code == 403
