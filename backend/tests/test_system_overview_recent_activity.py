from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import Request

from app import audit, errors
from app.routers import system


class AuditCursor:
    def __init__(self, items):
        self.items = items

    def sort(self, *args):
        return self

    def limit(self, *args):
        return self

    def __aiter__(self):
        self.iterator = iter(self.items)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration:
            raise StopAsyncIteration


@pytest.mark.asyncio
async def test_overview_excludes_invalid_session_noise(monkeypatch):
    find = Mock(return_value=AuditCursor([{
        "id": "audit-1", "action": "asset.created", "object_name": "sample.jpg",
    }]))
    monkeypatch.setattr(system, "db", SimpleNamespace(audit_logs=SimpleNamespace(find=find)))

    result = await system.system_overview({
        "id": "user-1", "roles": ["custom"], "menu_permissions": ["overview", "logs"],
        "action_permissions": [],
    })

    find.assert_called_once_with({"action": {"$ne": "auth.session_invalid"}})
    assert [item["action"] for item in result["recent_activity"]] == ["asset.created"]


@pytest.mark.asyncio
async def test_missing_credentials_do_not_generate_session_invalid_audit(monkeypatch):
    record = AsyncMock()
    monkeypatch.setattr(audit, "record_system_audit", record)
    request = Request({"type": "http", "method": "GET", "path": "/api/v1/system/overview", "headers": []})
    request.state.request_id = "request-1"

    response = await errors.app_error_handler(request, errors.AppError(401, "AUTH_REQUIRED", "请先登录"))

    assert response.status_code == 401
    record.assert_not_awaited()
