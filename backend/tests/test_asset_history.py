from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.routers import assets


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_args):
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
async def test_history_can_read_records_beyond_first_hundred(monkeypatch):
    rows = [{"id": str(index)} for index in range(205)]
    logs = SimpleNamespace(find=MagicMock(side_effect=lambda _: Cursor(rows)), count_documents=AsyncMock(return_value=205))
    monkeypatch.setattr(assets, "db", SimpleNamespace(assets=SimpleNamespace(find_one=AsyncMock(return_value={"id": "asset"})), audit_logs=logs))
    result = await assets.asset_operation_history("asset", {}, page=3, page_size=100)
    assert result["total"] == 205
    assert [item["id"] for item in result["items"]] == [str(i) for i in range(200, 205)]
    logs.find.assert_called_with({"object_type": "asset", "object_id": "asset"})
