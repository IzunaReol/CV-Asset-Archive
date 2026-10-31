from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.routers import assets


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_args):
        return self

    def skip(self, *_args):
        return self

    def limit(self, *_args):
        return self

    async def to_list(self, length=None):
        return self.rows[:length]


@pytest.mark.asyncio
async def test_model_options_searches_only_active_models_and_returns_one_page(monkeypatch):
    collection = SimpleNamespace(
        count_documents=AsyncMock(return_value=73),
        find=MagicMock(return_value=Cursor([{"id": "m51", "name": "fire.pt", "remark": "烟火"}])),
    )
    monkeypatch.setattr(assets, "db", SimpleNamespace(assets=collection))
    result = await assets.model_options({"id": "admin"}, q="fire.*", page=2, page_size=50)
    assert result == {"items": [{"id": "m51", "name": "fire.pt", "remark": "烟火"}], "total": 73, "page": 2, "page_size": 50}
    query = collection.count_documents.await_args.args[0]
    assert query["type"] == "model" and query["archived_at"] is None
    assert query["$or"][0]["name"]["$regex"] == "fire\\.\\*"
    collection.find.assert_called_once_with(query, {"_id": 0, "id": 1, "name": 1, "remark": 1})
