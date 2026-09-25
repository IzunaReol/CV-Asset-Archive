import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import main
from app.errors import AppError


def test_readiness_checks_all_dependencies_after_one_failure(monkeypatch):
    redis = MagicMock()
    redis.ping = AsyncMock(return_value=True)
    redis.aclose = AsyncMock()
    monkeypatch.setattr(main, "ping_database", AsyncMock(side_effect=RuntimeError("mongo down")))
    monkeypatch.setattr(main.storage, "bucket_exists", MagicMock(return_value=True))
    monkeypatch.setattr(main.Redis, "from_url", MagicMock(return_value=redis))

    with pytest.raises(AppError) as captured:
        asyncio.run(main.ready())

    assert captured.value.details == {"mongodb": False, "minio": True, "redis": True}
    main.storage.bucket_exists.assert_called_once()
    redis.ping.assert_awaited_once()
    redis.aclose.assert_awaited_once()


def test_readiness_reports_invalid_redis_configuration(monkeypatch):
    monkeypatch.setattr(main, "ping_database", AsyncMock(return_value=True))
    monkeypatch.setattr(main.storage, "bucket_exists", MagicMock(return_value=True))
    monkeypatch.setattr(main.Redis, "from_url", MagicMock(side_effect=ValueError("invalid redis url")))

    with pytest.raises(AppError) as captured:
        asyncio.run(main.ready())

    assert captured.value.status_code == 503
    assert captured.value.details == {"mongodb": True, "minio": True, "redis": False}
