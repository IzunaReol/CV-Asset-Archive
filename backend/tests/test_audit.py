from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import audit


@pytest.mark.asyncio
async def test_record_audit_sets_object_name_and_retention(monkeypatch):
    inserted = {}
    audit_logs = SimpleNamespace(insert_one=AsyncMock(side_effect=lambda item: inserted.update(item)))
    assets = SimpleNamespace(find_one=AsyncMock(return_value={"name": "示例素材.jpg"}))
    monkeypatch.setattr(audit, "db", SimpleNamespace(audit_logs=audit_logs, assets=assets))
    monkeypatch.setattr(audit.settings, "audit_log_retention_days", 180)

    await audit.record_audit(
        actor={"id": "user-1", "username": "admin"}, action="asset.created",
        object_type="asset", object_id="asset-1", request_id="request-1",
    )

    assert inserted["object_name"] == "示例素材.jpg"
    assert inserted["expires_at"] - inserted["created_at"] == timedelta(days=180)


@pytest.mark.asyncio
async def test_resolve_batch_audit_name_uses_count():
    assert await audit.resolve_audit_object_name("asset", "batch", {"count": 3}) == "批量素材（3 项）"
