from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.errors import AppError
from app.routers import datasets
from app.schemas import DatasetPublishRequest


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *args):
        return self

    async def to_list(self, length=None):
        return self.rows


@pytest.mark.asyncio
async def test_publication_quality_reports_unlabeled_and_duplicate_assets(monkeypatch):
    assets = [
        {"id": "a", "name": "one.jpg", "type": "image", "size": 10, "sha256": "x"},
        {"id": "b", "name": "two.jpg", "type": "image", "size": 10, "sha256": "x"},
        {"id": "c", "name": "three.jpg", "type": "image", "size": 10},
        {"id": "ann", "name": "labels.json", "type": "annotation", "size": 1},
    ]
    memberships = SimpleNamespace(distinct=AsyncMock(return_value=[item["id"] for item in assets]), find=lambda *args: Cursor([{"asset_id": item["id"]} for item in assets if item["type"] == "image"]))
    asset_collection = MagicMock()
    asset_collection.find.side_effect = [Cursor(assets), Cursor([{"id": "ann"}])]
    relations = MagicMock()
    relations.find.return_value = Cursor([{"source_id": "ann", "target_id": "a"}])
    monkeypatch.setattr(datasets, "db", SimpleNamespace(dataset_memberships=memberships, assets=asset_collection, relations=relations))

    report, _ = await datasets._publication_quality("dataset")
    assert report["blockers"] == []
    assert report["warnings"] == ["unlabeled_images", "duplicate_assets", "unassigned_images"]
    assert [item["id"] for item in report["issues"]["unlabeled_images"]] == ["b", "c"]
    assert [item["id"] for item in report["issues"]["duplicate_assets"]] == ["b"]
    assert report["missing_hash_count"] == 2
    assert len(report["token"]) == 64


@pytest.mark.asyncio
async def test_publication_quality_blocks_invalid_member(monkeypatch):
    memberships = SimpleNamespace(distinct=AsyncMock(return_value=["missing"]))
    asset_collection = MagicMock()
    asset_collection.find.return_value = Cursor([])
    monkeypatch.setattr(datasets, "db", SimpleNamespace(dataset_memberships=memberships, assets=asset_collection))

    report, _ = await datasets._publication_quality("dataset")
    assert report["blockers"] == ["empty_dataset", "invalid_assets"]
    assert report["issues"]["invalid_assets"] == [{"id": "missing"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("token,acknowledged,expected", [
    ("old" * 21 + "o", True, "DATASET_QUALITY_CHANGED"),
    ("a" * 64, False, "DATASET_QUALITY_ACK_REQUIRED"),
])
async def test_publish_rechecks_quality_and_requires_risk_ack(monkeypatch, token, acknowledged, expected):
    monkeypatch.setattr(datasets, "_get_dataset", AsyncMock(return_value={"id": "dataset"}))
    monkeypatch.setattr(datasets, "_publication_quality", AsyncMock(return_value=({
        "token": "a" * 64, "warnings": ["unlabeled_images"],
    }, [{"id": "image", "type": "image"}])))
    monkeypatch.setattr(datasets, "db", SimpleNamespace(
        dataset_memberships=SimpleNamespace(distinct=AsyncMock(return_value=["image"]))
    ))
    body = DatasetPublishRequest(version="v1", quality_token=token, acknowledge_warnings=acknowledged)
    with pytest.raises(AppError) as error:
        await datasets.publish_version.__wrapped__(
            "dataset", body, SimpleNamespace(state=SimpleNamespace(request_id="request")),
            {"id": "user", "username": "user"},
        )
    assert error.value.code == expected
