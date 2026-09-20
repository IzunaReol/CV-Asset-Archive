import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.routers import datasets


def test_annotation_membership_changes_keeps_annotation_used_by_another_image(monkeypatch):
    memberships = SimpleNamespace(distinct=AsyncMock(return_value=["image-2", "annotation"]))
    assets = SimpleNamespace(find=MagicMock())
    assets.find.side_effect = [
        SimpleNamespace(to_list=AsyncMock(return_value=[{"id": "image-2"}])),
        SimpleNamespace(to_list=AsyncMock(return_value=[{"id": "annotation"}])),
        SimpleNamespace(to_list=AsyncMock(return_value=[{"id": "annotation"}])),
    ]
    relations = SimpleNamespace(find=MagicMock(return_value=SimpleNamespace(to_list=AsyncMock(return_value=[{"source_id": "annotation"}]))))
    monkeypatch.setattr(datasets, "db", SimpleNamespace(dataset_memberships=memberships, assets=assets, relations=relations))

    changes = asyncio.run(datasets.annotation_membership_changes("dataset"))

    assert changes == {"added": [], "removed": []}


def test_annotation_membership_changes_removes_orphan_without_changing_version(monkeypatch):
    memberships = SimpleNamespace(distinct=AsyncMock(return_value=["image", "annotation"]))
    assets = SimpleNamespace(find=MagicMock())
    assets.find.side_effect = [
        SimpleNamespace(to_list=AsyncMock(return_value=[{"id": "image"}])),
        SimpleNamespace(to_list=AsyncMock(return_value=[])),
        SimpleNamespace(to_list=AsyncMock(return_value=[{"id": "annotation"}])),
    ]
    relations = SimpleNamespace(find=MagicMock(return_value=SimpleNamespace(to_list=AsyncMock(return_value=[]))))
    database = SimpleNamespace(dataset_memberships=memberships, assets=assets, relations=relations, dataset_version_memberships=SimpleNamespace(delete_many=AsyncMock()))
    monkeypatch.setattr(datasets, "db", database)

    changes = asyncio.run(datasets.annotation_membership_changes("dataset"))

    assert changes == {"added": [], "removed": ["annotation"]}
    database.dataset_version_memberships.delete_many.assert_not_awaited()
