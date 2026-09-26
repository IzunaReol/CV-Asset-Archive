from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.errors import AppError
from app.routers import relations
from app.schemas import RelationCreate, RelationType


def relation(source: str = "annotation-1", target: str = "image-1", kind: str = "annotates") -> RelationCreate:
    return RelationCreate(source_id=source, target_id=target, relation_type=kind)


def test_relation_asset_summary_handles_collection_objects() -> None:
    assert relations.relation_asset_summary({"id": "v1", "kind": "dataset_version"}) == {
        "id": "v1",
        "name": "v1",
        "type": "dataset_version",
        "tags": {},
    }


@pytest.mark.asyncio
async def test_annotation_dataset_effect_reports_addition(monkeypatch) -> None:
    memberships = SimpleNamespace(
        distinct=AsyncMock(side_effect=[["dataset-1", "deleted"], ["image-1"]])
    )
    datasets = SimpleNamespace(
        find_one=AsyncMock(side_effect=[{"id": "dataset-1", "name": "训练集"}, None])
    )
    monkeypatch.setattr(relations, "db", SimpleNamespace(dataset_memberships=memberships, datasets=datasets))

    result = await relations.annotation_dataset_effect("annotation-1", "image-1")

    assert result == [
        {"dataset_id": "dataset-1", "dataset_name": "训练集", "added": ["annotation-1"], "removed": []}
    ]


@pytest.mark.asyncio
async def test_preview_relation_rejects_self_reference(monkeypatch) -> None:
    result = await relations.preview_relation_item(
        RelationCreate.model_construct(
            source_id="same",
            target_id="same",
            relation_type=RelationType.ANNOTATES,
            provenance={},
        )
    )
    assert result["code"] == "SELF_RELATION"


@pytest.mark.asyncio
async def test_preview_relation_reports_missing_object(monkeypatch) -> None:
    empty = SimpleNamespace(find_one=AsyncMock(return_value=None))
    monkeypatch.setattr(
        relations,
        "db",
        SimpleNamespace(assets=empty, dataset_versions=empty, datasets=empty, collections=empty),
    )
    result = await relations.preview_relation_item(relation())
    assert result["code"] == "OBJECT_NOT_FOUND"


@pytest.mark.asyncio
async def test_preview_relation_reports_existing_relation(monkeypatch) -> None:
    assets = SimpleNamespace(
        find_one=AsyncMock(side_effect=[
            {"id": "annotation-1", "type": "annotation"},
            {"id": "image-1", "type": "image"},
        ])
    )
    empty = SimpleNamespace(find_one=AsyncMock(return_value=None))
    relation_store = SimpleNamespace(find_one=AsyncMock(return_value={"id": "relation-1"}))
    monkeypatch.setattr(
        relations,
        "db",
        SimpleNamespace(
            assets=assets,
            dataset_versions=empty,
            datasets=empty,
            collections=empty,
            relations=relation_store,
        ),
    )
    result = await relations.preview_relation_item(relation())
    assert result["code"] == "RELATION_EXISTS"
    assert result["existing_relation_id"] == "relation-1"


@pytest.mark.asyncio
async def test_validate_relation_rejects_wrong_direction(monkeypatch) -> None:
    assets = SimpleNamespace(
        find_one=AsyncMock(side_effect=[
            {"id": "image-1", "type": "image"},
            {"id": "annotation-1", "type": "annotation"},
        ])
    )
    empty = SimpleNamespace(find_one=AsyncMock(return_value=None))
    monkeypatch.setattr(
        relations,
        "db",
        SimpleNamespace(assets=assets, dataset_versions=empty, datasets=empty, collections=empty),
    )
    with pytest.raises(AppError) as exc_info:
        await relations.validate_relation(relation("image-1", "annotation-1"))
    assert exc_info.value.code == "RELATION_TYPE_MISMATCH"


@pytest.mark.asyncio
async def test_validate_relation_accepts_published_dataset_version(monkeypatch) -> None:
    assets = SimpleNamespace(find_one=AsyncMock(side_effect=[{"id": "model-1", "type": "model"}, None]))
    versions = SimpleNamespace(
        find_one=AsyncMock(return_value={"id": "version-1", "kind": "dataset_version", "dataset_id": "dataset-1"})
    )
    datasets = SimpleNamespace(find_one=AsyncMock(return_value={"id": "dataset-1"}))
    empty = SimpleNamespace(find_one=AsyncMock(return_value=None))
    monkeypatch.setattr(
        relations,
        "db",
        SimpleNamespace(assets=assets, dataset_versions=versions, datasets=datasets, collections=empty),
    )
    await relations.validate_relation(relation("model-1", "version-1", "trained_on"))
