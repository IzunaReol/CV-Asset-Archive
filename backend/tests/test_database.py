from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import database


@pytest.mark.asyncio
async def test_ensure_indexes_creates_all_required_indexes(monkeypatch):
    collections = {
        name: SimpleNamespace(create_index=AsyncMock(return_value="index"))
        for name in (
            "users", "refresh_sessions", "assets", "relations", "collections", "datasets",
            "dataset_memberships", "dataset_versions", "dataset_version_memberships", "jobs",
            "asset_selection_sets", "upload_sessions", "tag_definitions", "audit_logs",
        )
    }
    monkeypatch.setattr(database, "db", SimpleNamespace(**collections))

    await database.ensure_indexes()

    assert collections["users"].create_index.await_count == 1
    assert collections["assets"].create_index.await_count == 5
    assert collections["relations"].create_index.await_count == 3
    assert collections["jobs"].create_index.await_count == 5
    normalized_index = collections["assets"].create_index.await_args_list[3].args[0]
    assert ("normalized_name", 1) in normalized_index
    assert collections["relations"].create_index.await_args_list[0].kwargs == {"unique": True}
    assert collections["upload_sessions"].create_index.await_args.kwargs == {"expireAfterSeconds": 0}


@pytest.mark.asyncio
async def test_ping_database_uses_admin_command(monkeypatch):
    command = AsyncMock(return_value={"ok": 1})
    monkeypatch.setattr(database, "client", SimpleNamespace(admin=SimpleNamespace(command=command)))

    assert await database.ping_database() is True
    command.assert_awaited_once_with("ping")
