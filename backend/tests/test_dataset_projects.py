from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.errors import AppError
from app.routers import datasets


@pytest.mark.asyncio
async def test_dataset_projects_must_match_tag_values(monkeypatch):
    collection = SimpleNamespace(find_one=AsyncMock(return_value={"key": "project", "values": ["烟火检测", "安全帽"]}))
    monkeypatch.setattr(datasets, "db", SimpleNamespace(tag_definitions=collection))

    await datasets._validate_projects(["烟火检测", "安全帽"])
    with pytest.raises(AppError) as error:
        await datasets._validate_projects(["不存在的项目"])
    assert error.value.code == "DATASET_PROJECT_INVALID"


@pytest.mark.asyncio
async def test_dataset_projects_require_configured_values(monkeypatch):
    collection = SimpleNamespace(find_one=AsyncMock(return_value={"key": "project", "values": []}))
    monkeypatch.setattr(datasets, "db", SimpleNamespace(tag_definitions=collection))
    with pytest.raises(AppError) as error:
        await datasets._validate_projects(["烟火检测"])
    assert error.value.code == "DATASET_PROJECT_UNAVAILABLE"
