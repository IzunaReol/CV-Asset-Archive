import re
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from pymongo import DESCENDING

from ..audit import record_audit
from ..database import db
from ..dependencies import AdminUser, ManageUser, ReadUser
from ..errors import AppError
from ..schemas import AssetType, Role
from ..security import hash_password
from ..utils import new_id, now, public_document

router = APIRouter(tags=["administration"])


class UserCreate(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9_.-]{3,50}$")
    password: str = Field(min_length=8, max_length=128)
    roles: list[Role] = Field(min_length=1)


class UserUpdate(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9_.-]{3,50}$")
    password: str | None = Field(default=None, min_length=8, max_length=128)
    roles: list[Role] = Field(min_length=1)
    status: str = Field(pattern=r"^(active|disabled)$")


class FormatUpdate(BaseModel):
    remark: str = Field(default="", max_length=200)
    extensions: list[str] = Field(default_factory=list, max_length=100)


class FormatCreate(FormatUpdate):
    asset_type: AssetType


FORMAT_TYPES = {
    AssetType.IMAGE,
    AssetType.VIDEO,
    AssetType.ANNOTATION,
    AssetType.MODEL,
    AssetType.ARCHIVE,
    AssetType.IMAGE_ANNOTATION,
}
FORMAT_TYPE_NAMES = {
    "image": "图片",
    "video": "视频",
    "annotation": "标注",
    "model": "模型",
    "archive": "压缩文件",
    "image_annotation": "图片+标注",
}


def normalize_extensions(values: list[str]) -> list[str]:
    extensions: list[str] = []
    for value in values:
        normalized = f".{value.strip().lower().lstrip('.')}"
        if normalized != "." and normalized not in extensions:
            extensions.append(normalized)
    return extensions


async def ensure_extensions_removable(asset_type: str, removed: list[str]) -> None:
    for extension in removed:
        escaped = re.escape(extension)
        if await db.assets.count_documents(
            {"type": asset_type, "name": {"$regex": f"{escaped}$", "$options": "i"}}, limit=1
        ):
            raise AppError(
                409,
                "FORMAT_EXTENSION_IN_USE",
                f"格式 {extension} 已被现有{FORMAT_TYPE_NAMES[asset_type]}素材使用，不允许删除",
            )


@router.get("/users")
async def list_users(user: AdminUser) -> dict[str, Any]:
    return {
        "items": [public_document(item) async for item in db.users.find().sort("created_at", -1)]
    }


@router.post("/users", status_code=201)
async def create_user(body: UserCreate, request: Request, user: AdminUser) -> dict[str, Any]:
    if await db.users.find_one({"username": body.username}):
        raise AppError(409, "USER_EXISTS", "用户名已经存在")
    document = {
        "id": new_id(),
        "username": body.username,
        "password_hash": hash_password(body.password),
        "roles": [role.value for role in body.roles],
        "status": "active",
        "must_change_password": True,
        "created_at": now(),
        "updated_at": now(),
    }
    await db.users.insert_one(document)
    await record_audit(
        actor=user,
        action="user.created",
        object_type="user",
        object_id=document["id"],
        request_id=request.state.request_id,
    )
    return public_document(document) or {}


@router.patch("/users/{user_id}")
async def update_user(user_id: str, body: UserUpdate, request: Request, user: AdminUser) -> dict[str, Any]:
    target = await db.users.find_one({"id": user_id})
    if target is None:
        raise AppError(404, "USER_NOT_FOUND", "用户不存在")
    if target["username"] == "admin":
        raise AppError(403, "ADMIN_USER_PROTECTED", "admin 用户不允许编辑")
    duplicate = await db.users.find_one({"username": body.username, "id": {"$ne": user_id}})
    if duplicate:
        raise AppError(409, "USER_EXISTS", "用户名已经存在")
    changes: dict[str, Any] = {"username": body.username, "roles": [role.value for role in body.roles], "status": body.status, "updated_at": now()}
    if body.password:
        changes["password_hash"] = hash_password(body.password)
        changes["must_change_password"] = True
    await db.users.update_one({"id": user_id}, {"$set": changes})
    await record_audit(actor=user, action="user.updated", object_type="user", object_id=user_id, request_id=request.state.request_id)
    return public_document(await db.users.find_one({"id": user_id})) or {}


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: str, request: Request, user: AdminUser) -> None:
    target = await db.users.find_one({"id": user_id})
    if target is None:
        raise AppError(404, "USER_NOT_FOUND", "用户不存在")
    if target["username"] == "admin":
        raise AppError(403, "ADMIN_USER_PROTECTED", "admin 用户不允许删除")
    await db.users.delete_one({"id": user_id})
    await db.refresh_sessions.delete_many({"user_id": user_id})
    await record_audit(actor=user, action="user.deleted", object_type="user", object_id=user_id, request_id=request.state.request_id)


@router.get("/format-definitions")
async def list_format_definitions(user: ReadUser) -> dict[str, Any]:
    return {"items": [public_document(item) async for item in db.format_definitions.find({"asset_type": {"$ne": "other"}}).sort("asset_type", 1)]}


@router.post("/format-definitions", status_code=201)
async def create_format_definition(body: FormatCreate, request: Request, user: AdminUser) -> dict[str, Any]:
    if body.asset_type not in FORMAT_TYPES:
        raise AppError(400, "FORMAT_TYPE_INVALID", "只允许创建图片、视频、标注或模型格式")
    if await db.format_definitions.find_one({"asset_type": body.asset_type.value}):
        raise AppError(409, "FORMAT_DEFINITION_EXISTS", "该素材类别已经存在")
    extensions = normalize_extensions(body.extensions)
    conflict = await db.format_definitions.find_one(
        {"asset_type": {"$nin": ["archive", "image_annotation"]}, "extensions": {"$in": extensions}}
    ) if extensions and body.asset_type not in {AssetType.ARCHIVE, AssetType.IMAGE_ANNOTATION} else None
    if conflict:
        raise AppError(409, "FORMAT_EXTENSION_EXISTS", "文件格式不能同时属于多个素材类别")
    document = {"id": new_id(), "asset_type": body.asset_type.value, "remark": body.remark.strip(), "extensions": extensions, "built_in": False, "protected_extensions": [], "created_at": now(), "updated_at": now()}
    await db.format_definitions.insert_one(document)
    await record_audit(actor=user, action="format.created", object_type="format_definition", object_id=body.asset_type.value, request_id=request.state.request_id)
    return public_document(document) or {}


@router.patch("/format-definitions/{asset_type}")
async def update_format_definition(asset_type: AssetType, body: FormatUpdate, request: Request, user: AdminUser) -> dict[str, Any]:
    if asset_type not in FORMAT_TYPES:
        raise AppError(400, "FORMAT_TYPE_INVALID", "只允许维护图片、视频、标注或模型格式")
    current = await db.format_definitions.find_one({"asset_type": asset_type.value})
    if current is None:
        raise AppError(404, "FORMAT_DEFINITION_NOT_FOUND", "格式类别不存在")
    if current.get("built_in"):
        raise AppError(409, "BUILT_IN_FORMAT_PROTECTED", "内置格式类别不允许修改")
    extensions = normalize_extensions(body.extensions)
    protected_extensions = set(current.get("protected_extensions", []))
    removed_protected = sorted(protected_extensions - set(extensions))
    if removed_protected:
        raise AppError(409, "BUILT_IN_FORMAT_PROTECTED", f"内置文件格式 {removed_protected[0]} 不允许删除")
    conflict = await db.format_definitions.find_one(
        {"asset_type": {"$ne": asset_type.value}, "extensions": {"$in": extensions}}
    ) if extensions and asset_type not in {AssetType.ARCHIVE, AssetType.IMAGE_ANNOTATION} else None
    if conflict:
        raise AppError(409, "FORMAT_EXTENSION_EXISTS", "文件格式不能同时属于多个素材类别")
    await ensure_extensions_removable(asset_type.value, sorted(set(current.get("extensions", [])) - set(extensions)))
    await db.format_definitions.update_one({"asset_type": asset_type.value}, {"$set": {"remark": body.remark.strip(), "extensions": extensions, "updated_at": now()}})
    item = await db.format_definitions.find_one({"asset_type": asset_type.value})
    await record_audit(actor=user, action="format.updated", object_type="format_definition", object_id=asset_type.value, request_id=request.state.request_id)
    return public_document(item) or {}


@router.delete("/format-definitions/{asset_type}", status_code=204)
async def delete_format_definition(asset_type: AssetType, request: Request, user: AdminUser) -> None:
    if asset_type not in FORMAT_TYPES:
        raise AppError(400, "FORMAT_TYPE_INVALID", "只允许维护图片、视频、标注或模型格式")
    definition = await db.format_definitions.find_one({"asset_type": asset_type.value})
    if definition and definition.get("built_in"):
        raise AppError(409, "BUILT_IN_FORMAT_PROTECTED", "内置格式类别不允许删除")
    if await db.assets.count_documents({"type": asset_type.value}, limit=1):
        raise AppError(409, "FORMAT_DEFINITION_IN_USE", "该类别存在现有素材，不允许删除")
    result = await db.format_definitions.delete_one({"asset_type": asset_type.value})
    if not result.deleted_count:
        raise AppError(404, "FORMAT_DEFINITION_NOT_FOUND", "格式类别不存在")
    await record_audit(actor=user, action="format.deleted", object_type="format_definition", object_id=asset_type.value, request_id=request.state.request_id)


@router.get("/roles")
async def list_roles(user: AdminUser) -> dict[str, Any]:
    return {
        "items": [
            {
                "key": role.value,
                "name": {
                    "admin": "管理员",
                    "data_manager": "数据管理员",
                    "annotator": "标注员",
                    "ml_engineer": "算法工程师",
                    "viewer": "只读访客",
                }[role.value],
            }
            for role in Role
        ]
    }


@router.get("/audit-logs")
async def list_audit_logs(
    user: ManageUser,
    actor_id: str | None = None,
    object_type: str | None = None,
    action: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    query = {
        key: value
        for key, value in {
            "actor_id": actor_id,
            "object_type": object_type,
            "action": action,
        }.items()
        if value
    }
    total = await db.audit_logs.count_documents(query)
    cursor = (
        db.audit_logs.find(query)
        .sort("created_at", DESCENDING)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "items": [public_document(item) async for item in cursor],
        "page": page,
        "page_size": page_size,
        "total": total,
    }
