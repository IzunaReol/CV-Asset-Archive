import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .config import get_settings

settings = get_settings()
hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_access_token(user_id: str, username: str, roles: list[str]) -> tuple[str, datetime]:
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "username": username,
        "roles": roles,
        "type": "access",
        "exp": expires_at,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256"), expires_at


def decode_access_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
