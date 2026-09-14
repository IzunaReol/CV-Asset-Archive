from typing import Annotated, Any, Callable

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .database import db
from .errors import AppError
from .schemas import Role
from .security import decode_access_token

bearer = HTTPBearer(auto_error=False)


async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> dict[str, Any]:
    if credentials is None:
        raise AppError(401, "AUTH_REQUIRED", "请先登录")
    try:
        claims = decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise AppError(401, "TOKEN_INVALID", "登录状态已失效") from exc
    user = await db.users.find_one({"id": claims["sub"], "status": "active"})
    if user is None:
        raise AppError(401, "TOKEN_INVALID", "用户不存在或已停用")
    return user


def require_roles(*roles: Role) -> Callable:
    allowed = {role.value for role in roles}

    async def dependency(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
        if not allowed.intersection(user.get("roles", [])):
            raise AppError(403, "PERMISSION_DENIED", "当前角色无权执行此操作")
        return user

    return dependency


ReadUser = Annotated[dict[str, Any], Depends(current_user)]
WriteUser = Annotated[
    dict[str, Any],
    Depends(require_roles(Role.ADMIN, Role.DATA_MANAGER, Role.ANNOTATOR, Role.ML_ENGINEER)),
]
ManageUser = Annotated[dict[str, Any], Depends(require_roles(Role.ADMIN, Role.DATA_MANAGER))]
AdminUser = Annotated[dict[str, Any], Depends(require_roles(Role.ADMIN))]
