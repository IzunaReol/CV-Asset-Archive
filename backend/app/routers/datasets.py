import asyncio
import hashlib
import json
from functools import wraps
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, Field
from celery import Celery
from fastapi import APIRouter, Query, Request
from pymongo import ASCENDING, DESCENDING

from ..audit import record_audit
from ..config import get_settings
from ..database import db
from ..dependencies import ReadUser, WriteUser
from ..errors import AppError
from ..schemas import (
    DatasetCreate,
    DatasetExportRequest,
    DatasetMembersRequest,
    DatasetModelLinkRequest,
    DatasetPublishRequest,
    DatasetRestoreRequest,
    DatasetUpdate,
)
from ..storage import presigned_get
from .assets import asset_filter_clause
from ..utils import new_id, now, public_document

router = APIRouter(prefix="/datasets", tags=["datasets"])
settings = get_settings()
celery_client = Celery(broker=settings.redis_url)


def serialize_dataset_write(function):
    @wraps(function)
    async def guarded(dataset_id, *args, **kwargs):
        token = new_id()
        acquired = await db.datasets.update_one(
            {"id": dataset_id, "deleted_at": None, "write_token": None},
            {"$set": {"write_token": token}},
        )
        if not acquired.modified_count:
            await _get_dataset(dataset_id)
            raise AppError(409, "DATASET_BUSY", "数据集正在处理，请稍后重试")
        try:
            return await function(dataset_id, *args, **kwargs)
        finally:
            await db.datasets.update_one({"id": dataset_id, "write_token": token}, {"$unset": {"write_token": ""}})
    return guarded


async def _validate_status(value: str) -> None:
    definition = await db.tag_definitions.find_one({"key": "status"})
    values = (definition or {}).get("values", [])
    if values and value not in values:
        raise AppError(400, "DATASET_STATUS_INVALID", "状态不在标签管理的可选值中")


async def _get_dataset(dataset_id: str) -> dict[str, Any]:
    dataset = await db.datasets.find_one({"id": dataset_id, "deleted_at": None})
    if dataset is None:
        raise AppError(404, "DATASET_NOT_FOUND", "数据集不存在")
    return dataset


def _asset_snapshot(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": asset.get("name", ""),
        "type": asset.get("type", "other"),
        "size": int(asset.get("size") or 0),
        "sha256": asset.get("sha256"),
        "tags": asset.get("tags") or {},
        "remark": asset.get("remark") or "",
        "updated_at": asset.get("updated_at"),
    }


def _content_digest(items: list[dict[str, Any]]) -> str:
    content = [{"asset_id": item["asset_id"], "snapshot": item["snapshot"]} for item in items]
    payload = json.dumps(content, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()


async def annotation_membership_changes(dataset_id: str, image_ids: list[str] | None = None) -> dict[str, list[str]]:
    """Compare annotation memberships with effective image-to-annotation relations."""
    if image_ids is None:
        member_ids = await db.dataset_memberships.distinct("asset_id", {"dataset_id": dataset_id})
        images = await db.assets.find({"id": {"$in": member_ids}, "type": "image", "archived_at": None}, {"id": 1}).to_list(length=None)
        image_ids = [item["id"] for item in images]
    relations = await db.relations.find({"relation_type": "annotates", "status": "active", "target_id": {"$in": image_ids}}, {"source_id": 1}).to_list(length=None)
    candidate_ids = list({item["source_id"] for item in relations})
    annotations = await db.assets.find({"id": {"$in": candidate_ids}, "type": "annotation", "archived_at": None}, {"id": 1}).to_list(length=None)
    desired = {item["id"] for item in annotations}
    existing_ids = await db.dataset_memberships.distinct("asset_id", {"dataset_id": dataset_id})
    existing_annotations = await db.assets.find({"id": {"$in": existing_ids}, "type": "annotation"}, {"id": 1}).to_list(length=None)
    current = {item["id"] for item in existing_annotations}
    return {"added": sorted(desired - current), "removed": sorted(current - desired)}


async def sync_annotation_memberships(dataset_id: str, actor_id: str) -> dict[str, list[str]]:
    changes = await annotation_membership_changes(dataset_id)
    for annotation_id in changes["added"]:
        await db.dataset_memberships.update_one(
            {"dataset_id": dataset_id, "asset_id": annotation_id},
            {"$setOnInsert": {"id": new_id(), "dataset_id": dataset_id, "asset_id": annotation_id, "created_by": actor_id, "created_at": now()}},
            upsert=True,
        )
    if changes["removed"]:
        await db.dataset_memberships.delete_many({"dataset_id": dataset_id, "asset_id": {"$in": changes["removed"]}})
    if changes["added"] or changes["removed"]:
        await db.datasets.update_one({"id": dataset_id}, {"$set": {"updated_at": now()}})
    return changes


async def _dataset_summary(dataset: dict[str, Any]) -> dict[str, Any]:
    pipeline = [
        {"$match": {"dataset_id": dataset["id"]}},
        {"$lookup": {"from": "assets", "localField": "asset_id", "foreignField": "id", "as": "asset"}},
        {"$unwind": "$asset"},
        {"$match": {"asset.archived_at": None}},
        {"$group": {"_id": "$asset.type", "count": {"$sum": 1}, "size": {"$sum": {"$ifNull": ["$asset.size", 0]}}}},
    ]
    counts: dict[str, int] = {}
    total_size = 0
    cursor = await db.dataset_memberships.aggregate(pipeline)
    async for row in cursor:
        counts[row["_id"]] = row["count"]
        total_size += row["size"]
    result = public_document(dataset) or {}
    result.update({"member_count": sum(counts.values()), "counts": counts, "total_size": total_size})
    return result


@router.post("", status_code=201)
async def create_dataset(body: DatasetCreate, request: Request, user: WriteUser) -> dict[str, Any]:
    await _validate_status(body.status)
    timestamp = now()
    dataset = {
        "id": new_id(), "name": body.name.strip(), "remark": body.remark,
        "status": body.status, "current_version_id": None, "current_version": None,
        "created_by": user["id"], "created_by_name": user.get("username", user["id"]),
        "created_at": timestamp, "updated_at": timestamp, "deleted_at": None,
    }
    try:
        await db.datasets.insert_one(dataset)
    except Exception as exc:
        if "duplicate" in str(exc).lower() or "E11000" in str(exc):
            raise AppError(409, "DATASET_NAME_EXISTS", "数据集名称已存在") from exc
        raise
    await record_audit(actor=user, action="dataset.created", object_type="dataset", object_id=dataset["id"], request_id=request.state.request_id)
    return await _dataset_summary(dataset)


@router.get("")
async def list_datasets(
    user: ReadUser, q: str | None = None, status: str | None = None,
    creator: str | None = None, updated_from: str | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=0, le=200),
) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = [{"deleted_at": None}]
    if q:
        clauses.append({"$or": [{"name": {"$regex": q, "$options": "i"}}, {"remark": {"$regex": q, "$options": "i"}}]})
    if status:
        clauses.append({"status": status})
    if creator:
        clauses.append({"created_by_name": creator})
    if updated_from:
        from datetime import datetime
        try:
            clauses.append({"updated_at": {"$gte": datetime.fromisoformat(updated_from)}})
        except ValueError as exc:
            raise AppError(400, "DATE_INVALID", "更新时间格式不正确") from exc
    query = {"$and": clauses}
    total = await db.datasets.count_documents(query)
    cursor = db.datasets.find(query).sort([("updated_at", DESCENDING), ("id", ASCENDING)]).skip((page - 1) * page_size if page_size else 0).limit(page_size)
    return {"items": [await _dataset_summary(item) async for item in cursor], "page": page, "page_size": page_size, "total": total}


@router.get("/creators")
async def dataset_creators(user: ReadUser) -> dict[str, Any]:
    names = await db.datasets.distinct("created_by_name", {"deleted_at": None})
    return {"items": sorted(name for name in names if name)}


class DatasetCopyRequest(BaseModel):
    include_assets: bool = False
    name: str = Field(min_length=1, max_length=100)


@router.post("/{dataset_id}/copy", status_code=201)
@serialize_dataset_write
async def copy_dataset(dataset_id: str, body: DatasetCopyRequest, request: Request, user: WriteUser) -> dict[str, Any]:
    original = await _get_dataset(dataset_id)
    name = body.name.strip()
    if not name:
        raise AppError(400, "DATASET_NAME_EMPTY", "请输入数据集名称")
    copied = await create_dataset(DatasetCreate(name=name, remark=original.get("remark", ""), status=original["status"]), request, user)
    try:
        if body.include_assets:
            cursor = await db.dataset_memberships.aggregate([
                {"$match": {"dataset_id": dataset_id}},
                {"$lookup": {"from": "assets", "localField": "asset_id", "foreignField": "id", "as": "asset"}},
                {"$unwind": "$asset"},
                {"$match": {"asset.archived_at": None, "asset.type": {"$ne": "model"}}},
            ])
            batch = []
            async for item in cursor:
                batch.append({"id": new_id(), "dataset_id": copied["id"], "asset_id": item["asset_id"], "created_by": user["id"], "created_at": now()})
                if len(batch) == 1000:
                    await db.dataset_memberships.insert_many(batch)
                    batch = []
            if batch:
                await db.dataset_memberships.insert_many(batch)
            await sync_annotation_memberships(copied["id"], user["id"])
    except Exception:
        await db.dataset_memberships.delete_many({"dataset_id": copied["id"]})
        await db.datasets.delete_one({"id": copied["id"]})
        raise
    return await _dataset_summary(await _get_dataset(copied["id"]))


@router.get("/{dataset_id}/tag-distribution")
async def dataset_tag_distribution(dataset_id: str, user: ReadUser) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    cursor = await db.dataset_memberships.aggregate([
        {"$match": {"dataset_id": dataset_id}},
        {"$lookup": {"from": "assets", "localField": "asset_id", "foreignField": "id", "as": "asset"}},
        {"$unwind": "$asset"},
        {"$match": {"asset.archived_at": None}},
        {"$project": {"tags": {"$objectToArray": {"$ifNull": ["$asset.tags", {}]}}}},
        {"$unwind": "$tags"},
        {"$project": {"values": {"$cond": [{"$isArray": "$tags.v"}, "$tags.v", ["$tags.v"]]}}},
        {"$unwind": "$values"},
        {"$match": {"values": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$values", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
    ])
    return {"items": [[row["_id"], row["count"]] async for row in cursor]}


@router.get("/{dataset_id}")
async def get_dataset(dataset_id: str, user: ReadUser) -> dict[str, Any]:
    return await _dataset_summary(await _get_dataset(dataset_id))


@router.patch("/{dataset_id}")
@serialize_dataset_write
async def update_dataset(dataset_id: str, body: DatasetUpdate, request: Request, user: WriteUser) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    await _validate_status(body.status)
    await db.datasets.update_one({"id": dataset_id}, {"$set": {"name": body.name.strip(), "remark": body.remark, "status": body.status, "updated_at": now()}})
    await record_audit(actor=user, action="dataset.updated", object_type="dataset", object_id=dataset_id, request_id=request.state.request_id)
    return await _dataset_summary(await _get_dataset(dataset_id))


@router.delete("/{dataset_id}", status_code=204)
@serialize_dataset_write
async def delete_dataset(dataset_id: str, request: Request, user: WriteUser) -> None:
    await _get_dataset(dataset_id)
    version_ids = await db.dataset_versions.distinct("id", {"dataset_id": dataset_id})
    related_ids = [dataset_id, *version_ids]
    relation_result = await db.relations.delete_many({"$or": [
        {"source_id": {"$in": related_ids}},
        {"target_id": {"$in": related_ids}},
        {"provenance.dataset_id": dataset_id},
        {"provenance.dataset_version_id": {"$in": version_ids}},
    ]})
    await db.dataset_version_memberships.delete_many({"$or": [
        {"dataset_id": dataset_id}, {"version_id": {"$in": version_ids}},
    ]})
    await db.dataset_versions.delete_many({"dataset_id": dataset_id})
    await db.dataset_memberships.delete_many({"dataset_id": dataset_id})
    timestamp = now()
    await db.datasets.update_one({"id": dataset_id}, {"$set": {
        "deleted_at": timestamp, "updated_at": timestamp,
        "current_version_id": None, "current_version": None,
    }})
    await record_audit(actor=user, action="dataset.deleted", object_type="dataset", object_id=dataset_id, request_id=request.state.request_id, changes={"versions_deleted": len(version_ids), "relations_deleted": relation_result.deleted_count})


@router.get("/{dataset_id}/members")
async def list_members(dataset_id: str, user: ReadUser, page: int = Query(1, ge=1), page_size: int = Query(50, ge=0, le=200), q: str = "", asset_type: list[str] = Query(default=[]), tag: list[str] = Query(default=[]), match: str = Query("all", pattern="^(all|any)$"), no_tags: bool = False, ids_only: bool = False) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    clauses = [{"archived_at": None}, {"type": {"$ne": "annotation"}}]
    if q:
        import re
        clauses.append({"$or": [{"name": {"$regex": re.escape(q), "$options": "i"}}, {"remark": {"$regex": re.escape(q), "$options": "i"}}]})
    if asset_type:
        clauses.append({"type": {"$in": asset_type}})
    if no_tags:
        clauses.append({"$or": [{"tags": {}}, {"tags": None}]})
    rules = []
    for expression in tag:
        parts = expression.split(":", 2)
        if len(parts) != 3:
            raise AppError(400, "INVALID_TAG_FILTER", "筛选条件格式不正确")
        rules.append(asset_filter_clause(*parts))
    if rules:
        clauses.append({"$and" if match == "all" else "$or": rules})
    pipeline = [
        {"$match": {"dataset_id": dataset_id}},
        {"$lookup": {"from": "assets", "localField": "asset_id", "foreignField": "id", "as": "asset"}},
        {"$unwind": "$asset"},
        {"$replaceRoot": {"newRoot": "$asset"}},
        {"$match": {"$and": clauses}},
        {"$sort": {"created_at": -1, "id": 1}},

    ]
    count_cursor = await db.dataset_memberships.aggregate([*pipeline, {"$count": "count"}])
    counts = await count_cursor.to_list(length=1)
    total = counts[0]["count"] if counts else 0
    if page_size:
        pipeline.extend([{ "$skip": (page - 1) * page_size}, {"$limit": page_size}])
    cursor = await db.dataset_memberships.aggregate(pipeline)
    asset_documents = await cursor.to_list(length=None)
    if ids_only:
        return {"items": [{"id": item["id"]} for item in asset_documents], "page": page, "page_size": page_size, "total": total}
    assets: dict[str, dict[str, Any]] = {}
    for item in asset_documents:
        result = public_document(item) or {}
        preview_key = item.get("preview_key")
        if preview_key:
            result["preview_url"] = await asyncio.to_thread(presigned_get, preview_key)
        elif item.get("type") in {"image", "video"} and item.get("object_key"):
            result["preview_url"] = await asyncio.to_thread(presigned_get, item["object_key"])
        else:
            result["preview_url"] = None
        assets[item["id"]] = result
    image_ids = [item["id"] for item in assets.values() if item.get("type") == "image"]
    annotated_ids = set(await db.relations.distinct("target_id", {
        "target_id": {"$in": image_ids}, "relation_type": "annotates", "status": "active",
    })) if image_ids else set()
    for item in assets.values():
        item["has_annotation"] = item["id"] in annotated_ids
    return {"items": list(assets.values()), "page": page, "page_size": page_size, "total": total}


@router.post("/{dataset_id}/members/status")
async def member_status(dataset_id: str, body: DatasetMembersRequest, user: ReadUser) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    ids = list(dict.fromkeys(body.asset_ids))
    existing = await db.dataset_memberships.distinct("asset_id", {
        "dataset_id": dataset_id, "asset_id": {"$in": ids},
    }) if ids else []
    return {"existing_ids": existing}


@router.post("/{dataset_id}/members")
@serialize_dataset_write
async def add_members(dataset_id: str, body: DatasetMembersRequest, request: Request, user: WriteUser) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    ids = list(dict.fromkeys(body.asset_ids))
    assets = await db.assets.find({"id": {"$in": ids}, "archived_at": None}).to_list(length=len(ids))
    valid = [item for item in assets if item.get("type") not in {"model", "annotation"}]
    invalid_ids = sorted(set(ids) - {item["id"] for item in valid})
    timestamp = now()
    added = 0
    added_ids: list[str] = []
    for asset in valid:
        result = await db.dataset_memberships.update_one(
            {"dataset_id": dataset_id, "asset_id": asset["id"]},
            {"$setOnInsert": {"id": new_id(), "dataset_id": dataset_id, "asset_id": asset["id"], "created_by": user["id"], "created_at": timestamp}},
            upsert=True,
        )
        added += int(result.upserted_id is not None)
        if result.upserted_id is not None:
            added_ids.append(asset["id"])
    try:
        annotation_changes = await sync_annotation_memberships(dataset_id, user["id"])
    except Exception:
        if added_ids:
            await db.dataset_memberships.delete_many({"dataset_id": dataset_id, "asset_id": {"$in": added_ids}})
        await sync_annotation_memberships(dataset_id, user["id"])
        raise
    if added:
        await db.datasets.update_one({"id": dataset_id}, {"$set": {"updated_at": now()}})
    await record_audit(actor=user, action="dataset.members_added", object_type="dataset", object_id=dataset_id, request_id=request.state.request_id, changes={"added": added, "invalid_ids": invalid_ids})
    return {"added": added, "unchanged": len(valid) - added, "invalid_ids": invalid_ids, "annotations": annotation_changes}


@router.post("/{dataset_id}/members/preview")
async def preview_members(dataset_id: str, body: DatasetMembersRequest, user: ReadUser, action: str = Query("add", pattern="^(add|remove)$")) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    requested = set(body.asset_ids)
    assets = await db.assets.find({"id": {"$in": list(requested)}, "archived_at": None}).to_list(length=None)
    valid = {item["id"] for item in assets if item.get("type") not in {"model", "annotation"}}
    current = set(await db.dataset_memberships.distinct("asset_id", {"dataset_id": dataset_id}))
    if action == "add":
        future = current | valid
        changed = sorted(valid - current)
    else:
        future = current - valid
        changed = sorted(valid & current)
    images = await db.assets.find({"id": {"$in": list(future)}, "type": "image", "archived_at": None}, {"id": 1}).to_list(length=None)
    annotations = await annotation_membership_changes(dataset_id, [item["id"] for item in images])
    annotation_ids = [*annotations["added"], *annotations["removed"]]
    annotation_names = {item["id"]: item.get("name", item["id"]) for item in await db.assets.find({"id": {"$in": annotation_ids}}, {"id": 1, "name": 1}).to_list(length=None)}
    return {"action": action, "asset_ids": changed, "invalid_ids": sorted(requested - valid), "annotations": annotations, "annotation_names": annotation_names}


@router.delete("/{dataset_id}/members")
@serialize_dataset_write
async def remove_members(dataset_id: str, body: DatasetMembersRequest, request: Request, user: WriteUser) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    ids = list(set(body.asset_ids))
    if await db.assets.find_one({"id": {"$in": ids}, "type": "annotation"}):
        raise AppError(422, "ANNOTATION_MEMBERSHIP_DERIVED", "标注由图片关联关系决定，不能单独移出")
    removed_rows = await db.dataset_memberships.find({"dataset_id": dataset_id, "asset_id": {"$in": ids}}).to_list(length=None)
    result = await db.dataset_memberships.delete_many({"dataset_id": dataset_id, "asset_id": {"$in": ids}})
    try:
        annotation_changes = await sync_annotation_memberships(dataset_id, user["id"])
    except Exception:
        if removed_rows:
            await db.dataset_memberships.insert_many(removed_rows)
        await sync_annotation_memberships(dataset_id, user["id"])
        raise
    if result.deleted_count:
        await db.datasets.update_one({"id": dataset_id}, {"$set": {"updated_at": now()}})
    await record_audit(actor=user, action="dataset.members_removed", object_type="dataset", object_id=dataset_id, request_id=request.state.request_id, changes={"removed": result.deleted_count})
    return {"removed": result.deleted_count, "annotations": annotation_changes}


@router.post("/{dataset_id}/versions", status_code=201)
@serialize_dataset_write
async def publish_version(dataset_id: str, body: DatasetPublishRequest, request: Request, user: WriteUser) -> dict[str, Any]:
    dataset = await _get_dataset(dataset_id)
    member_ids = await db.dataset_memberships.distinct("asset_id", {"dataset_id": dataset_id})
    assets = (
        await db.assets.find({"id": {"$in": member_ids}, "archived_at": None, "type": {"$ne": "model"}})
        .sort("id", ASCENDING)
        .to_list(length=len(member_ids))
        if member_ids
        else []
    )
    invalid_ids = sorted(set(member_ids) - {item["id"] for item in assets})
    if invalid_ids:
        raise AppError(409, "DATASET_HAS_INVALID_ASSETS", "数据集中包含已删除或失效素材", {"asset_ids": invalid_ids})
    if not assets:
        raise AppError(400, "DATASET_EMPTY", "数据集中没有可发布的素材")
    members = [{"asset_id": asset["id"], "snapshot": _asset_snapshot(asset)} for asset in assets]
    digest = _content_digest(members)
    previous = await db.dataset_versions.find_one({"dataset_id": dataset_id}, sort=[("version_number", DESCENDING)])
    if previous and previous.get("content_digest") == digest:
        raise AppError(409, "DATASET_CONTENT_UNCHANGED", "数据集内容没有变化")
    number = int((previous or {}).get("version_number", 0)) + 1
    version_name = body.version if body.version.startswith("v") else f"v{body.version}"
    if await db.dataset_versions.find_one({"dataset_id": dataset_id, "version": version_name}):
        raise AppError(409, "DATASET_VERSION_EXISTS", "该版本号已存在")
    timestamp = now()
    version = {"id": new_id(), "dataset_id": dataset_id, "name": f"{dataset['name']} {version_name}", "kind": "dataset_version", "version": version_name, "version_number": number, "release_note": body.release_note, "member_count": len(members), "total_size": sum(m["snapshot"]["size"] for m in members), "content_digest": digest, "created_by": user["id"], "created_by_name": user.get("username", user["id"]), "created_at": timestamp}
    try:
        await db.dataset_versions.insert_one(version)
        if members:
            await db.dataset_version_memberships.insert_many([{"id": new_id(), "version_id": version["id"], "dataset_id": dataset_id, **member} for member in members])
        await db.datasets.update_one({"id": dataset_id}, {"$set": {"current_version_id": version["id"], "current_version": version["version"], "updated_at": timestamp}})
    except Exception:
        await db.dataset_version_memberships.delete_many({"version_id": version["id"]})
        await db.dataset_versions.delete_one({"id": version["id"]})
        await db.datasets.update_one({"id": dataset_id, "current_version_id": version["id"]}, {"$set": {"current_version_id": dataset.get("current_version_id"), "current_version": dataset.get("current_version"), "updated_at": dataset["updated_at"]}})
        raise
    await record_audit(actor=user, action="dataset.version_published", object_type="dataset_version", object_id=version["id"], request_id=request.state.request_id)
    return public_document(version) or {}


@router.get("/{dataset_id}/versions")
async def list_versions(dataset_id: str, user: ReadUser) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    return {"items": [public_document(item) async for item in db.dataset_versions.find({"dataset_id": dataset_id}).sort("version_number", DESCENDING)]}


@router.get("/{dataset_id}/models")
async def list_dataset_models(dataset_id: str, user: ReadUser) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    version_ids = await db.dataset_versions.distinct("id", {"dataset_id": dataset_id})
    relations = await db.relations.find(
        {"target_id": {"$in": version_ids}, "relation_type": "trained_on", "status": "active"}
    ).sort("created_at", DESCENDING).to_list(length=1000)
    model_ids = list({item["source_id"] for item in relations})
    models = {
        item["id"]: public_document(item)
        for item in (
            await db.assets.find({"id": {"$in": model_ids}, "type": "model"}).to_list(
                length=len(model_ids)
            )
            if model_ids
            else []
        )
    }
    versions = {
        item["id"]: item
        for item in (
            await db.dataset_versions.find({"id": {"$in": version_ids}}).to_list(
                length=len(version_ids)
            )
            if version_ids
            else []
        )
    }
    return {
        "items": [
            {
                "relation": public_document(relation),
                "model": models.get(relation["source_id"]),
                "version": public_document(versions.get(relation["target_id"])),
            }
            for relation in relations
            if relation["source_id"] in models
        ]
    }


@router.post("/{dataset_id}/models")
@serialize_dataset_write
async def add_dataset_model(
    dataset_id: str, body: DatasetModelLinkRequest, request: Request, user: WriteUser
) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    version = await db.dataset_versions.find_one(
        {"id": body.version_id, "dataset_id": dataset_id}
    )
    if version is None:
        raise AppError(404, "DATASET_VERSION_NOT_FOUND", "数据集版本不存在")
    model = await db.assets.find_one(
        {"id": body.model_id, "type": "model", "archived_at": None}
    )
    if model is None:
        raise AppError(404, "MODEL_NOT_FOUND", "模型不存在或已删除")

    previous_rows = await db.relations.find(
        {
            "source_id": body.model_id,
            "target_id": body.version_id,
            "relation_type": "trained_on",
        }
    ).sort("revision", DESCENDING).to_list(length=5)
    previous_by_target: dict[str, dict[str, Any]] = {}
    for relation in previous_rows:
        previous_by_target.setdefault(relation["target_id"], relation)

    timestamp = now()
    previous_primary = previous_by_target.get(body.version_id)
    link_id = (
        ((previous_primary or {}).get("provenance") or {}).get("dataset_model_link_id")
        or new_id()
    )
    provenance = {
        "source": "dataset",
        "remark": body.remark,
        "dataset_id": dataset_id,
        "dataset_version_id": body.version_id,
        "dataset_model_link_id": link_id,
    }
    created: list[dict[str, Any]] = []
    existing: list[str] = []
    for target_id in [body.version_id]:
        previous = previous_by_target.get(target_id)
        if previous and previous.get("status") == "active":
            existing.append(target_id)
            continue
        created.append(
            {
                "id": new_id(),
                "source_id": body.model_id,
                "target_id": target_id,
                "relation_type": "trained_on",
                "provenance": provenance,
                "revision": int((previous or {}).get("revision", 0)) + 1,
                "status": "active",
                "created_by": user["id"],
                "created_by_name": user["username"],
                "created_at": timestamp,
            }
        )
    if created:
        await db.relations.insert_many(created)
    if previous_primary and previous_primary.get("status") == "active":
        await db.relations.update_many(
            {
                "source_id": body.model_id,
                "relation_type": "trained_on",
                "status": "active",
                "provenance.dataset_id": dataset_id,
                "provenance.dataset_version_id": body.version_id,
            },
            {"$set": {"provenance": provenance}},
        )
        previous_primary["provenance"] = provenance
    primary = next(
        (item for item in created if item["target_id"] == body.version_id),
        previous_by_target.get(body.version_id),
    )
    await record_audit(
        actor=user,
        action="dataset.model_link_created",
        object_type="relation",
        object_id=(primary or {}).get("id", link_id),
        request_id=request.state.request_id,
        changes={"dataset_id": dataset_id, "version_id": body.version_id, "created": len(created)},
    )
    return {
        "relation": public_document(primary),
        "created": len(created),
        "existing": len(existing),
        "member_relations": 0,
    }


@router.delete("/{dataset_id}/models/{relation_id}")
@serialize_dataset_write
async def remove_dataset_model(
    dataset_id: str, relation_id: str, request: Request, user: WriteUser
) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    primary = await db.relations.find_one(
        {"id": relation_id, "relation_type": "trained_on", "status": "active"}
    )
    if primary is None:
        raise AppError(404, "RELATION_NOT_FOUND", "模型关联关系不存在")
    version = await db.dataset_versions.find_one(
        {"id": primary["target_id"], "dataset_id": dataset_id}
    )
    if version is None:
        raise AppError(400, "DATASET_MODEL_LINK_INVALID", "该关系不属于当前数据集")
    query: dict[str, Any] = {"id": relation_id, "status": "active"}
    timestamp = now()
    changes = {
        "status": "revoked",
        "revoked_at": timestamp,
        "revoked_by": user["id"],
        "revoke_reason": "",
        "replacement_relation_id": None,
    }
    result = await db.relations.update_many(query, {"$set": changes})
    await record_audit(
        actor=user,
        action="dataset.model_link_removed",
        object_type="relation",
        object_id=relation_id,
        request_id=request.state.request_id,
        changes={"dataset_id": dataset_id, "version_id": primary["target_id"], "revoked": result.modified_count},
    )
    return {"revoked": result.modified_count}


@router.get("/{dataset_id}/versions/{version_id}")
async def get_version(dataset_id: str, version_id: str, user: ReadUser) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    version = await db.dataset_versions.find_one({"id": version_id, "dataset_id": dataset_id})
    if version is None:
        raise AppError(404, "DATASET_VERSION_NOT_FOUND", "数据集版本不存在")
    items = [public_document(item) async for item in db.dataset_version_memberships.find({"version_id": version_id}).sort("asset_id", ASCENDING)]
    return {**(public_document(version) or {}), "members": items}


@router.get("/{dataset_id}/compare")
async def compare_versions(dataset_id: str, from_version_id: str, to_version_id: str, user: ReadUser) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    versions = await db.dataset_versions.find({"dataset_id": dataset_id, "id": {"$in": [from_version_id, to_version_id]}}).to_list(length=2)
    if len(versions) != 2 or from_version_id == to_version_id:
        raise AppError(400, "DATASET_VERSION_COMPARE_INVALID", "请选择两个不同的数据集版本")
    before = {m["asset_id"]: m async for m in db.dataset_version_memberships.find({"version_id": from_version_id})}
    after = {m["asset_id"]: m async for m in db.dataset_version_memberships.find({"version_id": to_version_id})}
    added, removed, unchanged, changed = [], [], [], []
    for asset_id in sorted(set(before) | set(after)):
        if asset_id not in before:
            added.append(after[asset_id])
        elif asset_id not in after:
            removed.append(before[asset_id])
        elif before[asset_id]["snapshot"] == after[asset_id]["snapshot"]:
            unchanged.append(after[asset_id])
        else:
            changed.append({"asset_id": asset_id, "before": before[asset_id]["snapshot"], "after": after[asset_id]["snapshot"]})
    return {"added": [public_document(i) for i in added], "removed": [public_document(i) for i in removed], "unchanged": [public_document(i) for i in unchanged], "changed": changed, "counts": {"added": len(added), "removed": len(removed), "unchanged": len(unchanged), "changed": len(changed), "total_changed": len(added)+len(removed)+len(changed)}}


@router.post("/{dataset_id}/restore")
@serialize_dataset_write
async def restore_version(dataset_id: str, body: DatasetRestoreRequest, request: Request, user: WriteUser) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    version = await db.dataset_versions.find_one({"id": body.version_id, "dataset_id": dataset_id})
    if version is None:
        raise AppError(404, "DATASET_VERSION_NOT_FOUND", "数据集版本不存在")
    members = await db.dataset_version_memberships.find({"version_id": body.version_id}).to_list(length=100000)
    backup = await db.dataset_memberships.find({"dataset_id": dataset_id}).to_list(length=None)
    valid_ids = await db.assets.distinct("id", {"id": {"$in": [item["asset_id"] for item in members]}, "archived_at": None, "type": {"$ne": "model"}})
    invalid = sorted({item["asset_id"] for item in members} - set(valid_ids))
    if invalid:
        raise AppError(409, "DATASET_HAS_INVALID_ASSETS", "版本中包含已删除或失效素材", {"asset_ids": invalid})
    timestamp = now()
    try:
        await db.dataset_memberships.delete_many({"dataset_id": dataset_id})
        workset_members = [{"id": new_id(), "dataset_id": dataset_id, "asset_id": item["asset_id"], "created_by": user["id"], "created_at": timestamp} for item in members if item["snapshot"].get("type") != "annotation"]
        if workset_members:
            await db.dataset_memberships.insert_many(workset_members)
        await sync_annotation_memberships(dataset_id, user["id"])
        await db.datasets.update_one({"id": dataset_id}, {"$set": {"updated_at": timestamp}})
    except Exception:
        await db.dataset_memberships.delete_many({"dataset_id": dataset_id})
        if backup:
            await db.dataset_memberships.insert_many(backup)
        raise
    await record_audit(actor=user, action="dataset.version_restored", object_type="dataset", object_id=dataset_id, request_id=request.state.request_id, changes={"version_id": body.version_id})
    return {"restored": len(members)}


@router.post("/{dataset_id}/export", status_code=202)
async def export_dataset(dataset_id: str, body: DatasetExportRequest, request: Request, user: WriteUser) -> dict[str, Any]:
    dataset = await _get_dataset(dataset_id)
    asset_ids = await db.dataset_memberships.distinct("asset_id", {"dataset_id": dataset_id})
    if not asset_ids:
        raise AppError(400, "DATASET_EMPTY", "数据集中没有可导出的素材")
    timestamp = now()
    job = {"id": new_id(), "type": "dataset_export", "name": body.name or f"{dataset['name']}-{timestamp.strftime('%Y%m%d%H%M%S')}", "state": "queued", "progress": 0, "owner_id": user["id"], "input": {"asset_ids": asset_ids, "asset_count": len(asset_ids), "dataset_id": dataset_id}, "result": None, "error": None, "created_at": timestamp, "updated_at": timestamp, "expires_at": timestamp + timedelta(hours=settings.export_expiry_hours)}
    await db.jobs.insert_one(job)
    try:
        await asyncio.to_thread(celery_client.send_task, "worker.tasks.build_export", args=[job["id"]])
    except Exception as exc:
        job["state"] = "failed"
        job["error"] = {"code": "TASK_DISPATCH_FAILED", "message": str(exc)[:500]}
        job["updated_at"] = now()
        await db.jobs.update_one({"id": job["id"]}, {"$set": {"state": job["state"], "error": job["error"], "updated_at": job["updated_at"]}})
    await record_audit(actor=user, action="dataset.export_created", object_type="job", object_id=job["id"], request_id=request.state.request_id, changes={"dataset_id": dataset_id, "asset_count": len(asset_ids)})
    return public_document(job) or {}
