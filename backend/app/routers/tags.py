from typing import Any

from fastapi import APIRouter, Request

from ..audit import record_audit
from ..database import db
from ..dependencies import AdminUser, ReadUser
from ..errors import AppError
from ..schemas import TagDefinitionCreate, TagDefinitionUpdate
from ..utils import new_id, now, public_document

router = APIRouter(prefix="/tag-definitions", tags=["tags"])


@router.get("")
async def list_tags(user: ReadUser) -> dict[str, Any]:
    return {
        "items": [public_document(item) async for item in db.tag_definitions.find().sort("name", 1)]
    }


@router.post("", status_code=201)
async def create_tag(
    body: TagDefinitionCreate, request: Request, user: AdminUser
) -> dict[str, Any]:
    if await db.tag_definitions.find_one({"key": body.key}):
        raise AppError(409, "TAG_DEFINITION_EXISTS", "标签字段已经存在")
    tag = {
        "id": new_id(),
        **body.model_dump(mode="json"),
        "created_by": user["id"],
        "created_at": now(),
        "updated_at": now(),
    }
    await db.tag_definitions.insert_one(tag)
    await record_audit(
        actor=user,
        action="tag_definition.created",
        object_type="tag_definition",
        object_id=tag["id"],
        request_id=request.state.request_id,
    )
    return public_document(tag) or {}


@router.patch("/{key}")
async def update_tag(
    key: str, body: TagDefinitionUpdate, request: Request, user: AdminUser
) -> dict[str, Any]:
    changes = body.model_dump(mode="json")
    changes["updated_at"] = now()
    result = await db.tag_definitions.update_one({"key": key}, {"$set": changes})
    if not result.matched_count:
        raise AppError(404, "TAG_DEFINITION_NOT_FOUND", "标签字段不存在")
    await record_audit(
        actor=user, action="tag_definition.updated", object_type="tag_definition",
        object_id=key, request_id=request.state.request_id,
        changes={"name": body.name, "values": body.values},
    )
    return public_document(await db.tag_definitions.find_one({"key": key})) or {}


@router.delete("/{key}", status_code=204)
async def delete_tag(key: str, request: Request, user: AdminUser) -> None:
    in_use = await db.assets.count_documents({f"tags.{key}": {"$exists": True}}, limit=1)
    if in_use:
        raise AppError(409, "TAG_DEFINITION_IN_USE", "标签正在使用，请先迁移或移除素材标签")
    result = await db.tag_definitions.delete_one({"key": key})
    if not result.deleted_count:
        raise AppError(404, "TAG_DEFINITION_NOT_FOUND", "标签字段不存在")
    await record_audit(
        actor=user,
        action="tag_definition.deleted",
        object_type="tag_definition",
        object_id=key,
        request_id=request.state.request_id,
    )
