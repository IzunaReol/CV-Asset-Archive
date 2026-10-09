from typing import Annotated, Any, Callable

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .database import db
from .errors import AppError
from .schemas import Role
from .permissions import ACTION_MENU, effective_action_permissions, effective_menu_permissions
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


def require_roles(*roles: Role, menu_permissions: tuple[str, ...] = ()) -> Callable:
    allowed = {role.value for role in roles}

    async def dependency(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
        has_role = bool(allowed.intersection(user.get("roles", [])))
        has_custom_menu = (
            Role.CUSTOM.value in user.get("roles", [])
            and bool(set(menu_permissions).intersection(user.get("menu_permissions", [])))
        )
        if not has_role and not has_custom_menu:
            raise AppError(403, "PERMISSION_DENIED", "当前角色无权执行此操作")
        return user

    return dependency


def require_menu(*menus: str) -> Callable:
    async def dependency(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
        if not set(menus).intersection(effective_menu_permissions(user)):
            raise AppError(403, "PERMISSION_DENIED", "当前账号没有此菜单的访问权限")
        return user
    return dependency


def require_action(*actions: str) -> Callable:
    async def dependency(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
        granted_actions = set(actions).intersection(effective_action_permissions(user))
        granted_menus = effective_menu_permissions(user)
        if not any(ACTION_MENU[action] in granted_menus for action in granted_actions):
            raise AppError(403, "PERMISSION_DENIED", "当前账号没有执行此操作的权限")
        return user
    return dependency


def ensure_action_access(user: dict[str, Any], action: str, *resource_menus: str) -> None:
    actions = effective_action_permissions(user)
    menus = effective_menu_permissions(user)
    required_menus = {ACTION_MENU[action], *resource_menus}
    if action not in actions or not required_menus.issubset(menus):
        raise AppError(403, "PERMISSION_DENIED", "当前账号没有执行此操作的权限")


def require_scoped_action(action: str, *resource_menus: str) -> Callable:
    async def dependency(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
        ensure_action_access(user, action, *resource_menus)
        return user
    return dependency


ReadUser = Annotated[dict[str, Any], Depends(current_user)]
WriteUser = Annotated[
    dict[str, Any],
    Depends(require_roles(Role.ADMIN, Role.DATA_MANAGER, Role.ANNOTATOR, Role.ML_ENGINEER, menu_permissions=("library", "datasets", "relations"))),
]
ManageUser = Annotated[dict[str, Any], Depends(require_roles(Role.ADMIN, Role.DATA_MANAGER))]
DestructiveUser = ManageUser
AdminUser = Annotated[dict[str, Any], Depends(require_roles(Role.ADMIN, menu_permissions=("admin",)))]
TagAdminUser = Annotated[dict[str, Any], Depends(require_roles(Role.ADMIN, menu_permissions=("tags",)))]
FormatAdminUser = Annotated[dict[str, Any], Depends(require_roles(Role.ADMIN, menu_permissions=("formats",)))]

AssetReadUser = Annotated[dict[str, Any], Depends(require_menu("library"))]
AssetUploadUser = Annotated[dict[str, Any], Depends(require_action("asset_upload"))]
AssetEditUser = Annotated[dict[str, Any], Depends(require_action("asset_edit"))]
AssetDeleteUser = Annotated[dict[str, Any], Depends(require_action("asset_delete"))]
DatasetReadUser = Annotated[dict[str, Any], Depends(require_menu("datasets"))]
SavedViewManageUser = Annotated[dict[str, Any], Depends(require_action("saved_view_manage"))]
DatasetCreateEditUser = Annotated[dict[str, Any], Depends(require_action("dataset_create_edit"))]
DatasetMembersUser = Annotated[dict[str, Any], Depends(require_action("dataset_members_manage"))]
DatasetVersionPublishUser = Annotated[dict[str, Any], Depends(require_action("dataset_version_publish"))]
DatasetVersionRestoreUser = Annotated[dict[str, Any], Depends(require_action("dataset_version_restore"))]
DatasetDeleteUser = Annotated[dict[str, Any], Depends(require_action("dataset_delete"))]
DatasetModelUser = Annotated[dict[str, Any], Depends(require_action("dataset_model_manage"))]
RelationReadUser = Annotated[dict[str, Any], Depends(require_menu("relations", "lineage"))]
RelationWriteUser = Annotated[dict[str, Any], Depends(require_action("relation_manage"))]
RelationRevokeUser = Annotated[dict[str, Any], Depends(require_action("relation_revoke"))]
JobReadUser = Annotated[dict[str, Any], Depends(require_menu("downloads"))]
ExportWriteUser = Annotated[dict[str, Any], Depends(require_action("export_create"))]
AssetExportUser = Annotated[dict[str, Any], Depends(require_scoped_action("export_create", "library"))]
DatasetExportUser = Annotated[dict[str, Any], Depends(require_scoped_action("export_create", "datasets"))]
TrashReadUser = Annotated[dict[str, Any], Depends(require_menu("trash"))]
TrashManageUser = Annotated[dict[str, Any], Depends(require_action("trash_manage"))]
TagReadUser = Annotated[dict[str, Any], Depends(require_menu("tags", "library", "datasets"))]
TagManageUser = Annotated[dict[str, Any], Depends(require_action("tag_manage"))]
FormatReadUser = Annotated[dict[str, Any], Depends(require_menu("formats", "library"))]
FormatManageUser = Annotated[dict[str, Any], Depends(require_action("format_manage"))]
UserManageUser = Annotated[dict[str, Any], Depends(require_action("user_manage"))]
SystemLogReadUser = Annotated[dict[str, Any], Depends(require_menu("logs"))]


def ensure_data_management_access(user: dict[str, Any]) -> None:
    if not {Role.ADMIN.value, Role.DATA_MANAGER.value}.intersection(user.get("roles", [])):
        raise AppError(403, "PERMISSION_DENIED", "仅管理员或数据管理员可以执行此操作")
