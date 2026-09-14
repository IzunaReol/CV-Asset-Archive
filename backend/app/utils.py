from datetime import UTC, datetime
from typing import Any
import secrets
import time
from uuid import UUID


def now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    random_a = secrets.randbits(12)
    random_b = secrets.randbits(62)
    value = (timestamp_ms << 80) | (0x7 << 76) | (random_a << 64) | (0b10 << 62) | random_b
    return str(UUID(int=value))


def public_document(document: dict[str, Any] | None) -> dict[str, Any] | None:
    if document is None:
        return None
    result = dict(document)
    result.pop("_id", None)
    result.pop("password_hash", None)
    result.pop("token_hash", None)
    return result
