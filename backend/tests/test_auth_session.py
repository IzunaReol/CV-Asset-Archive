import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import Response

from app.routers import auth


def test_issue_tokens_keeps_refresh_token_in_http_only_cookie(monkeypatch):
    insert_one = AsyncMock()
    monkeypatch.setattr(
        auth,
        "db",
        SimpleNamespace(refresh_sessions=SimpleNamespace(insert_one=insert_one)),
    )
    response = Response()
    user = {"id": "user-1", "username": "admin", "roles": ["admin"], "status": "active"}

    tokens = asyncio.run(auth.issue_tokens(user, response, remember=False))

    payload = tokens.model_dump()
    assert "refresh_token" not in payload
    cookie = response.headers["set-cookie"]
    assert f"{auth.REFRESH_COOKIE}=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Max-Age" not in cookie
    insert_one.assert_awaited_once()
