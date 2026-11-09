from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.routers import jobs
from app.schemas import ExportCreate, ExportSelection


@pytest.mark.asyncio
async def test_preview_only_counts_active_annotation_assets_for_selected_images(monkeypatch):
    assets = SimpleNamespace(distinct=AsyncMock(side_effect=[
        ["image-1"], ["annotation-1", "annotation-2"],
    ]))
    relations = SimpleNamespace(distinct=AsyncMock(return_value=["annotation-1", "annotation-2", "deleted-annotation"]))
    monkeypatch.setattr(jobs, "db", SimpleNamespace(assets=assets, relations=relations))
    result = await jobs.preview_export_annotations(
        ExportSelection(asset_ids=["image-1", "video-1"]), {"id": "user-1"},
    )
    assert result == {"annotation_count": 2}
    assert assets.distinct.await_args_list[0].args[1]["type"] == "image"
    assert assets.distinct.await_args_list[1].args[1]["type"] == "annotation"
    assert relations.distinct.await_args.args[1]["status"] == "active"


@pytest.mark.asyncio
async def test_export_snapshots_related_annotations_and_keeps_explicit_selection(monkeypatch):
    inserted = []
    database = SimpleNamespace(
        assets=SimpleNamespace(distinct=AsyncMock(side_effect=[
            ["image-1"], ["annotation-1"],
        ])),
        relations=SimpleNamespace(distinct=AsyncMock(return_value=["annotation-1"])),
        jobs=SimpleNamespace(insert_one=AsyncMock(side_effect=lambda job: inserted.append(job))),
    )
    monkeypatch.setattr(jobs, "db", database)
    monkeypatch.setattr(jobs, "record_audit", AsyncMock())
    monkeypatch.setattr(jobs.asyncio, "to_thread", AsyncMock())
    request = SimpleNamespace(state=SimpleNamespace(request_id="request-1"))
    user = {"id": "user-1"}

    await jobs.create_export(
        ExportCreate(name="含标注", asset_ids=["image-1", "annotation-1"], include_annotations=True),
        request, user,
    )
    assert inserted[-1]["input"]["annotation_ids"] == ["annotation-1"]
    assert inserted[-1]["input"]["asset_count"] == 2
    await jobs.create_export(
        ExportCreate(name="不含关联标注", asset_ids=["image-1"], include_annotations=False),
        request, user,
    )
    assert inserted[-1]["input"]["annotation_ids"] == []
    assert inserted[-1]["input"]["asset_count"] == 1
