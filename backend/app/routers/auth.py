import hashlib
import logging
from datetime import timedelta

from fastapi import APIRouter, Request, Response
from redis.asyncio import Redis

from ..config import get_settings
from ..database import db
from ..errors import AppError
from ..schemas import LoginRequest, TokenResponse
from ..security import create_access_token, hash_token, new_refresh_token, verify_password
from ..utils import now, public_document

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
REFRESH_COOKIE = "cv_archive_refresh"
logger = logging.getLogger("cv-archive.auth")


def _login_failure_key(request: Request, username: str) -> str:
    client = request.client.host if request.client else "unknown"
    digest = hashlib.sha256(f"{client}:{username.strip().lower()}".encode()).hexdigest()
    return f"cv-archive:login-failures:{digest}"


async def _login_failure_count(key: str, *, increment: bool = False, clear: bool = False) -> int:
    redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=0.2,
        socket_timeout=0.2,
    )
    try:
        if clear:
            await redis.delete(key)
            return 0
        if increment:
            count = int(await redis.incr(key))
            if count == 1:
                await redis.expire(key, settings.login_failure_window_seconds)
            return count
        return int(await redis.get(key) or 0)
    except Exception as exc:
        logger.warning({"event": "login_rate_limit_unavailable", "error": type(exc).__name__})
        return 0
    finally:
        await redis.aclose()


async def issue_tokens(user: dict, response: Response, remember: bool) -> TokenResponse:
    access, access_expiry = create_access_token(user["id"], user["username"], user["roles"])
    refresh = new_refresh_token()
    await db.refresh_sessions.insert_one(
        {
            "id": hash_token(refresh)[:32],
            "user_id": user["id"],
            "token_hash": hash_token(refresh),
            "created_at": now(),
            "expires_at": now() + timedelta(days=settings.refresh_token_days),
            "remember": remember,
        }
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        httponly=True,
        secure=settings.app_env.lower() not in {"development", "test", "local"},
        samesite="strict",
        max_age=settings.refresh_token_days * 24 * 60 * 60 if remember else None,
        path="/api/v1/auth",
    )
    return TokenResponse(
        access_token=access,
        access_expires_at=access_expiry,
        user=public_document(user) or {},
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, response: Response) -> TokenResponse:
    failure_key = _login_failure_key(request, body.username)
    if await _login_failure_count(failure_key) >= settings.login_max_failures:
        raise AppError(429, "LOGIN_RATE_LIMITED", "登录失败次数过多，请稍后重试")
    user = await db.users.find_one({"username": body.username, "status": "active"})
    if user is None or not verify_password(body.password, user["password_hash"]):
        failures = await _login_failure_count(failure_key, increment=True)
        if failures >= settings.login_max_failures:
            raise AppError(429, "LOGIN_RATE_LIMITED", "登录失败次数过多，请稍后重试")
        raise AppError(401, "INVALID_CREDENTIALS", "用户名或密码错误")
    await _login_failure_count(failure_key, clear=True)
    return await issue_tokens(user, response, body.remember)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response) -> TokenResponse:
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if not refresh_token:
        raise AppError(401, "TOKEN_INVALID", "刷新令牌已失效")
    token_hash = hash_token(refresh_token)
    session = await db.refresh_sessions.find_one_and_delete(
        {"token_hash": token_hash, "expires_at": {"$gt": now()}}
    )
    if session is None:
        raise AppError(401, "TOKEN_INVALID", "刷新令牌已失效")
    user = await db.users.find_one({"id": session["user_id"], "status": "active"})
    if user is None:
        raise AppError(401, "TOKEN_INVALID", "用户不存在或已停用")
    return await issue_tokens(user, response, bool(session.get("remember", True)))


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> None:
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if refresh_token:
        await db.refresh_sessions.delete_one({"token_hash": hash_token(refresh_token)})
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
