from typing import Any

from fastapi import APIRouter, Request

from ..audit import record_audit
from ..database import db
from ..dependencies import ReadUser, WriteUser
from ..errors import AppError
from ..schemas import CollectionCreate, SavedViewCreate, SavedViewUpdate
from ..utils import new_id, now, public_document

router = APIRouter(tags=["collections"])


@router.post("/collections", status_code=201)
async def create_collection(
    body: CollectionCreate, request: Request, user: WriteUser
) -> dict[str, Any]:
    found = await db.assets.count_documents({"id": {"$in": body.asset_ids}, "archived_at": None})
    if found != len(set(body.asset_ids)):
        raise AppError(400, "INVALID_ASSET_SET", "集合中包含不存在或已归档的素材")
    previous = await db.collections.find_one({"name": body.name}, sort=[("revision", -1)])
    collection = {
        "id": new_id(),
        "name": body.name,
        "description": body.description,
        "kind": "snapshot" if body.freeze else "manual",
        "asset_ids": list(dict.fromkeys(body.asset_ids)),
        "revision": (previous or {}).get("revision", 0) + 1,
        "frozen_at": now() if body.freeze else None,
        "created_by": user["id"],
        "created_at": now(),
        "updated_at": now(),
    }
    await db.collections.insert_one(collection)
    await record_audit(
        actor=user,
        action="collection.created",
        object_type="collection",
        object_id=collection["id"],
        request_id=request.state.request_id,
    )
    return public_document(collection) or {}


@router.post("/collections/{collection_id}/freeze")
async def freeze_collection(
    collection_id: str, request: Request, user: WriteUser
) -> dict[str, Any]:
    result = await db.collections.update_one(
        {"id": collection_id, "frozen_at": None},
        {"$set": {"frozen_at": now(), "kind": "snapshot", "updated_at": now()}},
    )
    if not result.matched_count:
        existing = await db.collections.find_one({"id": collection_id})
        if existing is None:
            raise AppError(404, "COLLECTION_NOT_FOUND", "数据集不存在")
    await record_audit(
        actor=user,
        action="collection.frozen",
        object_type="collection",
        object_id=collection_id,
        request_id=request.state.request_id,
    )
    return public_document(await db.collections.find_one({"id": collection_id})) or {}


@router.get("/collections")
async def list_collections(user: ReadUser) -> dict[str, Any]:
    return {
        "items": [
            public_document(item)
            async for item in db.collections.find().sort("created_at", -1).limit(200)
        ]
    }


@router.post("/saved-views", status_code=201)
async def create_saved_view(
    body: SavedViewCreate, request: Request, user: WriteUser
) -> dict[str, Any]:
    view = {
        "id": new_id(),
        **body.model_dump(),
        "owner_id": user["id"],
        "created_at": now(),
        "updated_at": now(),
    }
    await db.saved_views.insert_one(view)
    await record_audit(
        actor=user,
        action="saved_view.created",
        object_type="saved_view",
        object_id=view["id"],
        request_id=request.state.request_id,
    )
    return public_document(view) or {}


@router.get("/saved-views")
async def list_saved_views(user: ReadUser) -> dict[str, Any]:
    query = {"$or": [{"owner_id": user["id"]}, {"shared": True}]}
    return {
        "items": [
            public_document(item)
            async for item in db.saved_views.find(query).sort("updated_at", -1)
        ]
    }


@router.patch("/saved-views/{view_id}")
async def update_saved_view(
    view_id: str, body: SavedViewUpdate, request: Request, user: WriteUser
) -> dict[str, Any]:
    result = await db.saved_views.update_one(
        {"id": view_id, "owner_id": user["id"]},
        {"$set": {"name": body.name, "updated_at": now()}},
    )
    if not result.matched_count:
        raise AppError(404, "SAVED_VIEW_NOT_FOUND", "保存视图不存在或无权修改")
    await record_audit(
        actor=user, action="saved_view.updated", object_type="saved_view",
        object_id=view_id, request_id=request.state.request_id,
        changes={"name": body.name},
    )
    return public_document(await db.saved_views.find_one({"id": view_id})) or {}


@router.delete("/saved-views/{view_id}", status_code=204)
async def delete_saved_view(view_id: str, request: Request, user: WriteUser) -> None:
    result = await db.saved_views.delete_one({"id": view_id, "owner_id": user["id"]})
    if not result.deleted_count:
        raise AppError(404, "SAVED_VIEW_NOT_FOUND", "保存视图不存在或无权删除")
    await record_audit(
        actor=user, action="saved_view.deleted", object_type="saved_view",
        object_id=view_id, request_id=request.state.request_id,
    )
