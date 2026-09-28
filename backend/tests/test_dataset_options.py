from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.routers import datasets


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *args):
        return self

    def skip(self, count):
        self.rows = self.rows[count:]
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    def __aiter__(self):
        self.iterator = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration:
            raise StopAsyncIteration


@pytest.mark.asyncio
async def test_dataset_options_returns_requested_page(monkeypatch):
    rows = [
        {"id": f"dataset-{index}", "name": f"数据集 {index}", "current_version_id": "v1"}
        for index in range(75)
    ]
    collection = SimpleNamespace(
        count_documents=AsyncMock(return_value=75),
        find=lambda *args: Cursor(rows.copy()),
    )
    monkeypatch.setattr(datasets, "db", SimpleNamespace(datasets=collection))

    result = await datasets.dataset_options({}, q="", page=2, page_size=50)

    assert result["total"] == 75
    assert len(result["items"]) == 25
    assert result["items"][0]["id"] == "dataset-50"
