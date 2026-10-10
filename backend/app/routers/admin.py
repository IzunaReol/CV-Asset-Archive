import asyncio
import csv
import io
import json
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from pymongo import DESCENDING

from ..audit import record_audit, resolve_audit_object_name
from ..database import db
from ..dependencies import (
    FormatManageUser,
    FormatReadUser,
    ReadUser,
    RoleManageUser,
    RoleReadUser,
    SystemLogReadUser,
    UserManageUser,
    UserReadUser,
)
from ..errors import AppError
from ..permissions import (
    ACTION_DEFINITIONS,
    ACTION_MENU,
    MENU_DEFINITIONS,
    ROLE_ACTION_PERMISSIONS,
    ROLE_MENU_PERMISSIONS,
    ActionPermission,
    MenuPermission,
    effective_action_permissions,
    effective_menu_permissions,
)
from ..schemas import AssetType, Role
from ..security import hash_password
from ..utils import new_id, now, public_document

router = APIRouter(tags=["administration"])

class UserPermissionsMixin(BaseModel):
    roles: list[Role] = Field(min_length=1, max_length=1)
    role_template_id: str | None = None
    menu_permissions: list[MenuPermission] = Field(default_factory=list)
    action_permissions: list[ActionPermission] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_menu_permissions(self):
        role = self.roles[0]
        if role is Role.CUSTOM:
            self.menu_permissions = list(dict.fromkeys(self.menu_permissions))
            self.action_permissions = list(dict.fromkeys(self.action_permissions))
            if "dataset_manage" in self.action_permissions:
                self.action_permissions = [key for key in self.action_permissions if key != "dataset_manage"]
                self.action_permissions.extend([
                    "dataset_create_edit", "dataset_members_manage", "dataset_version_publish",
                    "dataset_version_restore", "dataset_delete", "dataset_model_manage",
                ])
                self.action_permissions = list(dict.fromkeys(self.action_permissions))
            if not self.menu_permissions:
                raise ValueError("自定义角色请至少选择一个菜单权限")
            invalid = [key for key in self.action_permissions if ACTION_MENU[key] not in self.menu_permissions]
            if invalid:
                raise ValueError("操作权限必须先启用对应菜单")
        else:
            self.menu_permissions = list(ROLE_MENU_PERMISSIONS[role.value])
            self.action_permissions = list(ROLE_ACTION_PERMISSIONS[role.value])
        return self


class UserCreate(UserPermissionsMixin):
    username: str = Field(pattern=r"^[a-zA-Z0-9_.-]{3,50}$")
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(UserPermissionsMixin):
    username: str = Field(pattern=r"^[a-zA-Z0-9_.-]{3,50}$")
    password: str | None = Field(default=None, min_length=8, max_length=128)
    status: str = Field(pattern=r"^(active|disabled)$")


class FormatUpdate(BaseModel):
    remark: str = Field(default="", max_length=200)
    extensions: list[str] = Field(default_factory=list, max_length=100)


class FormatCreate(FormatUpdate):
    asset_type: AssetType


class RoleTemplateBody(BaseModel):
    name: str = Field(min_length=2, max_length=50)
    description: str = Field(default="", max_length=200)
    menu_permissions: list[MenuPermission] = Field(min_length=1)
    action_permissions: list[ActionPermission] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_permissions(self):
        self.menu_permissions = list(dict.fromkeys(self.menu_permissions))
        self.action_permissions = list(dict.fromkeys(self.action_permissions))
        if invalid := [key for key in self.action_permissions if ACTION_MENU[key] not in self.menu_permissions]:
            raise ValueError(f"操作权限缺少对应菜单：{','.join(invalid)}")
        return self


@router.post("/role-impact/{role_ref}")
async def preview_role_impact(role_ref: str, body: RoleTemplateBody, user: RoleManageUser) -> dict[str, Any]:
    if role_ref.startswith("fixed:"):
        role_key = role_ref.removeprefix("fixed:")
        if role_key not in {role.value for role in Role} or role_key in {Role.ADMIN.value, Role.CUSTOM.value}:
            raise AppError(404, "ROLE_NOT_FOUND", "角色不存在")
        current = await db.role_overrides.find_one({"key": role_key}) or {}
        current_menus = current.get("menu_permissions", ROLE_MENU_PERMISSIONS[role_key])
        current_actions = current.get("action_permissions", ROLE_ACTION_PERMISSIONS[role_key])
        query = {"roles": role_key, "status": "active"}
    else:
        current = await db.role_templates.find_one({"id": role_ref})
        if current is None:
            raise AppError(404, "ROLE_TEMPLATE_NOT_FOUND", "角色不存在")
        current_menus = current.get("menu_permissions", [])
        current_actions = current.get("action_permissions", [])
        query = {"role_template_id": role_ref, "status": "active"}
    users = await db.users.find(query, {"_id": 0, "username": 1}).sort("username", 1).limit(50).to_list(length=50)
    return {
        "affected_count": await db.users.count_documents(query),
        "usernames": [item["username"] for item in users],
        "menus_added": sorted(set(body.menu_permissions) - set(current_menus)),
        "menus_removed": sorted(set(current_menus) - set(body.menu_permissions)),
        "actions_added": sorted(set(body.action_permissions) - set(current_actions)),
        "actions_removed": sorted(set(current_actions) - set(body.action_permissions)),
    }


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
async def list_users(user: UserReadUser) -> dict[str, Any]:
    return {
        "items": [public_document(item) async for item in db.users.find().sort("created_at", -1)]
    }


@router.post("/users", status_code=201)
async def create_user(body: UserCreate, request: Request, user: UserManageUser) -> dict[str, Any]:
    if await db.users.find_one({"username": body.username}):
        raise AppError(409, "USER_EXISTS", "用户名已经存在")
    document = {
        "id": new_id(),
        "username": body.username,
        "password_hash": hash_password(body.password),
        "roles": [role.value for role in body.roles],
        "role_template_id": body.role_template_id if body.roles[0] is Role.CUSTOM else None,
        "menu_permissions": body.menu_permissions,
        "action_permissions": body.action_permissions,
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
        object_name=document["username"],
        changes={
            "username": document["username"],
            "roles": document["roles"],
            "menu_permissions": document["menu_permissions"],
            "action_permissions": document["action_permissions"],
            "status": document["status"],
        },
    )
    return public_document(document) or {}


@router.patch("/users/{user_id}")
async def update_user(user_id: str, body: UserUpdate, request: Request, user: UserManageUser) -> dict[str, Any]:
    target = await db.users.find_one({"id": user_id})
    if target is None:
        raise AppError(404, "USER_NOT_FOUND", "用户不存在")
    if target["username"] == "admin":
        raise AppError(403, "ADMIN_USER_PROTECTED", "admin 用户不允许编辑")
    duplicate = await db.users.find_one({"username": body.username, "id": {"$ne": user_id}})
    if duplicate:
        raise AppError(409, "USER_EXISTS", "用户名已经存在")
    changes: dict[str, Any] = {"username": body.username, "roles": [role.value for role in body.roles], "role_template_id": body.role_template_id if body.roles[0] is Role.CUSTOM else None, "menu_permissions": body.menu_permissions, "action_permissions": body.action_permissions, "status": body.status, "updated_at": now()}
    if body.password:
        changes["password_hash"] = hash_password(body.password)
        changes["must_change_password"] = True
    await db.users.update_one({"id": user_id}, {"$set": changes})
    await db.refresh_sessions.delete_many({"user_id": user_id})
    await record_audit(
        actor=user, action="user.updated", object_type="user", object_id=user_id,
        object_name=body.username, request_id=request.state.request_id,
        changes={
            "username": body.username,
            "roles": [role.value for role in body.roles],
            "menu_permissions": body.menu_permissions,
            "action_permissions": body.action_permissions,
            "status": body.status,
            "password_changed": bool(body.password),
        },
    )
    return public_document(await db.users.find_one({"id": user_id})) or {}


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: str, request: Request, user: UserManageUser) -> None:
    target = await db.users.find_one({"id": user_id})
    if target is None:
        raise AppError(404, "USER_NOT_FOUND", "用户不存在")
    if target["username"] == "admin":
        raise AppError(403, "ADMIN_USER_PROTECTED", "admin 用户不允许删除")
    await db.users.delete_one({"id": user_id})
    await db.refresh_sessions.delete_many({"user_id": user_id})
    await record_audit(
        actor=user, action="user.deleted", object_type="user", object_id=user_id,
        object_name=target["username"], request_id=request.state.request_id,
        changes={"username": target["username"], "roles": target.get("roles", [])},
    )


@router.get("/format-definitions")
async def list_format_definitions(user: FormatReadUser) -> dict[str, Any]:
    return {"items": [public_document(item) async for item in db.format_definitions.find({"asset_type": {"$ne": "other"}}).sort("asset_type", 1)]}


@router.post("/format-definitions", status_code=201)
async def create_format_definition(body: FormatCreate, request: Request, user: FormatManageUser) -> dict[str, Any]:
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
async def update_format_definition(asset_type: AssetType, body: FormatUpdate, request: Request, user: FormatManageUser) -> dict[str, Any]:
    if asset_type not in FORMAT_TYPES:
        raise AppError(400, "FORMAT_TYPE_INVALID", "只允许维护图片、视频、标注或模型格式")
    current = await db.format_definitions.find_one({"asset_type": asset_type.value})
    if current is None:
        raise AppError(404, "FORMAT_DEFINITION_NOT_FOUND", "格式类别不存在")
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
async def delete_format_definition(asset_type: AssetType, request: Request, user: FormatManageUser) -> None:
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
async def list_roles(user: RoleReadUser) -> dict[str, Any]:
    custom_templates = [public_document(item) async for item in db.role_templates.find({}).sort("name", 1)]
    overrides = {item["key"]: item async for item in db.role_overrides.find({})}
    role_names = {
        "admin": "管理员", "data_manager": "数据管理员", "annotator": "标注员",
        "ml_engineer": "算法工程师", "viewer": "只读访客", "custom": "自定义",
    }
    fixed_roles = []
    for role in Role:
        override = overrides.get(role.value, {})
        if override.get("disabled") or role is Role.CUSTOM:
            continue
        fixed_roles.append({
            "key": role.value, "name": override.get("name", role_names[role.value]),
            "description": override.get("description", ""), "built_in": role is Role.ADMIN,
            "menu_permissions": override.get("menu_permissions", ROLE_MENU_PERMISSIONS[role.value]),
            "action_permissions": override.get("action_permissions", ROLE_ACTION_PERMISSIONS[role.value]),
        })
    return {
        "items": fixed_roles,
        "menus": MENU_DEFINITIONS,
        "actions": ACTION_DEFINITIONS,
        "templates": [
            {
                "key": role.value,
                "name": f"复制{role_name}权限",
                "built_in": True,
                "menu_permissions": ROLE_MENU_PERMISSIONS[role.value],
                "action_permissions": ROLE_ACTION_PERMISSIONS[role.value],
            }
            for role, role_name in [
                (Role.DATA_MANAGER, "数据管理员"), (Role.ANNOTATOR, "标注员"),
                (Role.ML_ENGINEER, "算法工程师"), (Role.VIEWER, "只读访客"),
            ]
        ] + custom_templates,
    }


@router.post("/role-templates", status_code=201)
async def create_role_template(body: RoleTemplateBody, request: Request, user: RoleManageUser) -> dict[str, Any]:
    document = {"id": new_id(), **body.model_dump(), "built_in": False, "created_by": user["id"], "created_at": now(), "updated_at": now()}
    try:
        await db.role_templates.insert_one(document)
    except Exception as exc:
        if "duplicate" in str(exc).lower() or "E11000" in str(exc):
            raise AppError(409, "ROLE_TEMPLATE_EXISTS", "角色名称已存在") from exc
        raise
    await record_audit(actor=user, action="role_template.created", object_type="role_template", object_id=document["id"], object_name=body.name, changes=body.model_dump(), request_id=request.state.request_id)
    return public_document(document) or {}


@router.put("/role-templates/{template_id}")
async def update_role_template(template_id: str, body: RoleTemplateBody, request: Request, user: RoleManageUser) -> dict[str, Any]:
    result = await db.role_templates.find_one_and_update({"id": template_id}, {"$set": {**body.model_dump(), "updated_at": now()}}, return_document=True)
    if result is None:
        raise AppError(404, "ROLE_TEMPLATE_NOT_FOUND", "角色不存在")
    await db.users.update_many({"role_template_id": template_id}, {"$set": {"menu_permissions": body.menu_permissions, "action_permissions": body.action_permissions, "updated_at": now()}})
    await record_audit(actor=user, action="role_template.updated", object_type="role_template", object_id=template_id, object_name=body.name, changes=body.model_dump(), request_id=request.state.request_id)
    return public_document(result) or {}


@router.delete("/role-templates/{template_id}", status_code=204)
async def delete_role_template(template_id: str, request: Request, user: RoleManageUser) -> None:
    template = await db.role_templates.find_one({"id": template_id})
    if template is None:
        raise AppError(404, "ROLE_TEMPLATE_NOT_FOUND", "角色不存在")
    bound_users = await db.users.find({"role_template_id": template_id}, {"username": 1}).limit(20).to_list(length=20)
    if bound_users:
        names = "、".join(item["username"] for item in bound_users)
        raise AppError(409, "ROLE_IN_USE", f"已有用户{names}绑定该角色，不可删除", {"usernames": [item["username"] for item in bound_users]})
    await db.role_templates.delete_one({"id": template_id})
    await record_audit(actor=user, action="role_template.deleted", object_type="role_template", object_id=template_id, object_name=template.get("name", ""), request_id=request.state.request_id)


@router.put("/role-definitions/{role_key}")
async def update_role_definition(role_key: Role, body: RoleTemplateBody, request: Request, user: RoleManageUser) -> dict[str, Any]:
    if role_key in {Role.ADMIN, Role.CUSTOM}:
        raise AppError(403, "ADMIN_ROLE_PROTECTED", "管理员角色不允许修改")
    document = {"key": role_key.value, **body.model_dump(), "disabled": False, "updated_at": now()}
    await db.role_overrides.update_one({"key": role_key.value}, {"$set": document}, upsert=True)
    await db.users.update_many({"roles": role_key.value}, {"$set": {"menu_permissions": body.menu_permissions, "action_permissions": body.action_permissions, "updated_at": now()}})
    await record_audit(actor=user, action="role_template.updated", object_type="role_template", object_id=role_key.value, object_name=body.name, changes=body.model_dump(), request_id=request.state.request_id)
    return document


@router.delete("/role-definitions/{role_key}", status_code=204)
async def delete_role_definition(role_key: Role, request: Request, user: RoleManageUser) -> None:
    if role_key in {Role.ADMIN, Role.CUSTOM}:
        raise AppError(403, "ADMIN_ROLE_PROTECTED", "管理员角色不允许删除")
    bound_users = await db.users.find({"roles": role_key.value}, {"username": 1}).limit(20).to_list(length=20)
    if bound_users:
        names = "、".join(item["username"] for item in bound_users)
        raise AppError(409, "ROLE_IN_USE", f"已有用户{names}绑定该角色，不可删除", {"usernames": [item["username"] for item in bound_users]})
    await db.role_overrides.update_one({"key": role_key.value}, {"$set": {"key": role_key.value, "disabled": True, "updated_at": now()}}, upsert=True)
    await record_audit(actor=user, action="role_template.deleted", object_type="role_template", object_id=role_key.value, object_name=role_key.value, request_id=request.state.request_id)


@router.get("/permissions/me")
async def my_permissions(user: ReadUser) -> dict[str, Any]:
    menu_keys = effective_menu_permissions(user)
    action_keys = effective_action_permissions(user)
    return {
        "role": user.get("roles", [""])[0],
        "menus": [item for item in MENU_DEFINITIONS if item["key"] in menu_keys],
        "actions": [item for item in ACTION_DEFINITIONS if item["key"] in action_keys],
        "updated_at": user.get("updated_at"),
    }


def _audit_log_query(
    q: str = Query("", max_length=200),
    actor_id: str | None = None,
    object_type: str | None = None,
    action: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> dict[str, Any]:
    if created_from and created_to and created_from > created_to:
        raise AppError(400, "INVALID_TIME_RANGE", "开始时间不能晚于结束时间")
    query: dict[str, Any] = {
        key: value
        for key, value in {
            "actor_id": actor_id,
            "object_type": object_type,
            "action": action,
        }.items()
        if value
    }
    if q.strip():
        pattern = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [
            {"actor_username": pattern}, {"action": pattern}, {"object_type": pattern},
            {"object_id": pattern}, {"object_name": pattern}, {"request_id": pattern},
        ]
    if created_from or created_to:
        query["created_at"] = {
            key: value for key, value in {"$gte": created_from, "$lte": created_to}.items()
            if value is not None
        }
    return query


@router.get("/audit-logs/export")
async def export_audit_logs(
    user: SystemLogReadUser,
    q: str = Query("", max_length=200),
    actor_id: str | None = None,
    object_type: str | None = None,
    action: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> StreamingResponse:
    query = _audit_log_query(q, actor_id, object_type, action, created_from, created_to)
    cursor = db.audit_logs.find(query).sort("created_at", DESCENDING).limit(10000)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(["时间", "操作用户", "操作", "操作对象类型", "操作对象", "结果", "请求状态", "客户端IP", "请求ID", "变更内容"])
    async for item in cursor:
        writer.writerow([
            item.get("created_at", ""), item.get("actor_username") or item.get("actor_id", ""),
            item.get("action", ""), item.get("object_type", ""), item.get("object_name", ""),
            item.get("outcome", "success"), item.get("response_status", ""), item.get("client_ip", ""),
            item.get("request_id", ""), json.dumps(item.get("changes") or {}, ensure_ascii=False, default=str),
        ])
    filename = f"audit-logs-{now().strftime('%Y%m%d-%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8")]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/audit-logs")
async def list_audit_logs(
    user: SystemLogReadUser,
    q: str = Query("", max_length=200),
    actor_id: str | None = None,
    object_type: str | None = None,
    action: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    query = _audit_log_query(q, actor_id, object_type, action, created_from, created_to)
    total = await db.audit_logs.count_documents(query)
    cursor = (
        db.audit_logs.find(query)
        .sort("created_at", DESCENDING)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [public_document(item) async for item in cursor]
    missing_names = [item for item in items if item and not item.get("object_name")]
    names = await asyncio.gather(*[
        resolve_audit_object_name(item["object_type"], item["object_id"], item.get("changes"))
        for item in missing_names
    ])
    for item, name in zip(missing_names, names, strict=True):
        item["object_name"] = name
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
    }
