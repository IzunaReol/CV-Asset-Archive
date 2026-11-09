from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import migrations
from app.bootstrap import DEFAULT_FORMATS, DEFAULT_TAGS


class AsyncRows:
    def __init__(self, rows):
        self.rows = rows

    def __aiter__(self):
        self.iterator = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration:
            raise StopAsyncIteration


@pytest.mark.asyncio
async def test_simple_migrations_apply_expected_updates(monkeypatch):
    database = SimpleNamespace(
        assets=SimpleNamespace(update_many=AsyncMock()),
        format_definitions=SimpleNamespace(update_one=AsyncMock()),
    )
    monkeypatch.setattr(migrations, "db", database)

    await migrations.migration_001_asset_defaults()
    await migrations.migration_003_archive_format_types()
    await migrations.migration_005_normalize_asset_names()

    database.assets.update_many.assert_any_await(
        {"archived_at": {"$exists": False}}, {"$set": {"archived_at": None}}
    )
    assert database.format_definitions.update_one.await_count == 1
    assert database.assets.update_many.await_count == 2


@pytest.mark.asyncio
async def test_model_format_and_tag_defaults_migrate_existing_install(monkeypatch):
    formats = SimpleNamespace(update_one=AsyncMock())
    tags = SimpleNamespace(
        find_one=AsyncMock(return_value={"values": ["YOLO11", "YOLOv8", "RT-DETR", "自研框架"]}),
        update_one=AsyncMock(),
    )
    monkeypatch.setattr(migrations, "db", SimpleNamespace(format_definitions=formats, tag_definitions=tags))
    await migrations.migration_006_model_formats_and_tag_defaults()
    assert formats.update_one.await_args.args[1]["$addToSet"]["extensions"]["$each"] == [
        ".caffemodel", ".solverstate", ".mdl",
    ]
    values = tags.update_one.await_args.args[1]["$set"]["values"]
    assert values[:3] == ["Caffe", "Darknet", "PyTorch"]
    assert "自研框架" in values
    assert not {"YOLO11", "YOLOv8", "RT-DETR"}.intersection(values)
    assert {".caffemodel", ".solverstate", ".mdl"}.issubset(DEFAULT_FORMATS["model"])
    assert next(item[2] for item in DEFAULT_TAGS if item[0] == "data_source") == [
        "开源数据", "生产数据", "客户反馈数据", "AIGC数据", "研发数据",
    ]


@pytest.mark.asyncio
async def test_relation_creator_migration_handles_known_and_unknown_users(monkeypatch):
    relations = SimpleNamespace(update_many=AsyncMock())
    monkeypatch.setattr(
        migrations,
        "db",
        SimpleNamespace(
            users=SimpleNamespace(find=lambda *args: AsyncRows([{"id": "u1", "username": "alice"}])),
            relations=relations,
        ),
    )

    await migrations.migration_002_relation_creator_names()

    assert relations.update_many.await_count == 3
    assert relations.update_many.await_args_list[1].args[0] == {"created_by": {"$nin": ["u1"]}}


@pytest.mark.asyncio
async def test_collection_migration_deduplicates_members(monkeypatch):
    memberships = SimpleNamespace(update_one=AsyncMock())
    datasets = SimpleNamespace(update_one=AsyncMock())
    monkeypatch.setattr(
        migrations,
        "db",
        SimpleNamespace(
            collections=SimpleNamespace(find=lambda query: AsyncRows([{
                "id": "dataset-1", "name": "历史集合", "asset_ids": ["a1", "a1", "a2"]
            }])),
            datasets=datasets,
            dataset_memberships=memberships,
        ),
    )

    await migrations.migration_004_collections_to_datasets()

    assert datasets.update_one.await_count == 1
    assert memberships.update_one.await_count == 2


@pytest.mark.asyncio
async def test_run_migrations_skips_applied_versions(monkeypatch):
    first = AsyncMock()
    second = AsyncMock()
    insert_one = AsyncMock()
    monkeypatch.setattr(migrations, "MIGRATIONS", [(1, "first", first), (2, "second", second)])
    monkeypatch.setattr(
        migrations,
        "db",
        SimpleNamespace(
            schema_migrations=SimpleNamespace(
                find=lambda *args: AsyncRows([{"version": 1}]), insert_one=insert_one
            )
        ),
    )

    await migrations.run_migrations()

    first.assert_not_awaited()
    second.assert_awaited_once()
    assert insert_one.await_args.args[0]["version"] == 2
