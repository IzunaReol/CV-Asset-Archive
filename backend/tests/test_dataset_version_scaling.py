from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.routers import datasets


class Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.skipped = 0
        self.limited = None

    def sort(self, *args):
        return self

    def skip(self, value):
        self.skipped = value
        return self

    def limit(self, value):
        self.limited = value
        return self

    def __aiter__(self):
        start = self.skipped
        stop = None if self.limited is None else start + self.limited
        self.iterator = iter(self.rows[start:stop])
        return self

    async def __anext__(self):
        if not hasattr(self, "iterator"):
            self.__aiter__()
        try:
            return next(self.iterator)
        except StopIteration:
            raise StopAsyncIteration


@pytest.mark.asyncio
async def test_version_detail_is_paginated(monkeypatch):
    rows = [
        {"asset_id": f"a-{index}", "snapshot": {"name": f"素材 {index}"}}
        for index in range(5)
    ]
    cursor = Cursor(rows)
    database = SimpleNamespace(
        datasets=SimpleNamespace(find_one=AsyncMock(return_value={"id": "dataset"})),
        dataset_versions=SimpleNamespace(
            find_one=AsyncMock(return_value={"id": "version", "dataset_id": "dataset"})
        ),
        dataset_version_memberships=SimpleNamespace(
            count_documents=AsyncMock(return_value=5),
            find=lambda *args, **kwargs: cursor,
        ),
    )
    monkeypatch.setattr(datasets, "db", database)

    result = await datasets.get_version(
        "dataset", "version", {"id": "user"}, page=2, page_size=2
    )

    assert [item["asset_id"] for item in result["members"]] == ["a-2", "a-3"]
    assert result["member_total"] == 5


@pytest.mark.asyncio
async def test_version_compare_streams_and_caps_details(monkeypatch):
    before = Cursor([
        {"asset_id": "a", "snapshot": {"name": "旧 A"}},
        {"asset_id": "b", "snapshot": {"name": "B"}},
    ])
    after = Cursor([
        {"asset_id": "a", "snapshot": {"name": "新 A"}},
        {"asset_id": "c", "snapshot": {"name": "C"}},
    ])
    cursors = iter([before, after])
    database = SimpleNamespace(
        datasets=SimpleNamespace(find_one=AsyncMock(return_value={"id": "dataset"})),
        dataset_versions=SimpleNamespace(
            find=lambda *args, **kwargs: SimpleNamespace(
                to_list=AsyncMock(return_value=[{"id": "v1"}, {"id": "v2"}])
            )
        ),
        dataset_version_memberships=SimpleNamespace(find=lambda *args, **kwargs: next(cursors)),
    )
    monkeypatch.setattr(datasets, "db", database)
    monkeypatch.setattr(datasets, "DATASET_COMPARE_DETAIL_LIMIT", 1)

    result = await datasets.compare_versions("dataset", "v1", "v2", {"id": "user"})

    assert result["counts"] == {
        "added": 1, "removed": 1, "unchanged": 0, "changed": 1, "total_changed": 3,
    }
    assert result["truncated"] is True
    assert sum(len(result[key]) for key in ("added", "removed", "unchanged", "changed")) == 1
