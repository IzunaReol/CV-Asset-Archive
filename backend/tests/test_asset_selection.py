import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.errors import AppError
from app.routers import assets
from app.utils import now


class SelectionSets:
    def __init__(self, row):
        self.row = row

    async def find_one(self, query):
        if query["id"] != self.row["id"] or query["owner_id"] != self.row["owner_id"]:
            return None
        return self.row if self.row["expires_at"] > now() else None


def test_selection_set_resolves_exclusions(monkeypatch):
    row = {
        "id": "selection", "owner_id": "user", "asset_ids": ["a", "b", "c"],
        "expires_at": now() + timedelta(minutes=5),
    }
    monkeypatch.setattr(assets, "db", SimpleNamespace(asset_selection_sets=SelectionSets(row)))
    result = asyncio.run(assets.resolve_selection_ids(
        {"id": "user"}, [], "selection", ["b"]
    ))
    assert result == ["a", "c"]


def test_selection_set_rejects_mixed_payload(monkeypatch):
    monkeypatch.setattr(assets, "db", SimpleNamespace())
    with pytest.raises(AppError) as exc:
        asyncio.run(assets.resolve_selection_ids(
            {"id": "user"}, ["a"], "selection", []
        ))
    assert exc.value.code == "SELECTION_CONFLICT"
