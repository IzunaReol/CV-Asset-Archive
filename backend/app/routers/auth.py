from datetime import timedelta

from fastapi import APIRouter, Request

from ..config import get_settings
from ..database import db
from ..errors import AppError
from ..schemas import LoginRequest, RefreshRequest, TokenResponse
from ..security import create_access_token, hash_token, new_refresh_token, verify_password
from ..utils import now, public_document

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


async def issue_tokens(user: dict) -> TokenResponse:
    access, access_expiry = create_access_token(user["id"], user["username"], user["roles"])
    refresh = new_refresh_token()
    await db.refresh_sessions.insert_one(
        {
            "id": hash_token(refresh)[:32],
            "user_id": user["id"],
            "token_hash": hash_token(refresh),
            "created_at": now(),
            "expires_at": now() + timedelta(days=settings.refresh_token_days),
        }
    )
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        access_expires_at=access_expiry,
        user=public_document(user) or {},
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    user = await db.users.find_one({"username": body.username, "status": "active"})
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise AppError(401, "INVALID_CREDENTIALS", "用户名或密码错误")
    return await issue_tokens(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest) -> TokenResponse:
    token_hash = hash_token(body.refresh_token)
    session = await db.refresh_sessions.find_one_and_delete(
        {"token_hash": token_hash, "expires_at": {"$gt": now()}}
    )
    if session is None:
        raise AppError(401, "TOKEN_INVALID", "刷新令牌已失效")
    user = await db.users.find_one({"id": session["user_id"], "status": "active"})
    if user is None:
        raise AppError(401, "TOKEN_INVALID", "用户不存在或已停用")
    return await issue_tokens(user)


@router.post("/logout", status_code=204)
async def logout(body: RefreshRequest, request: Request) -> None:
    await db.refresh_sessions.delete_one({"token_hash": hash_token(body.refresh_token)})
