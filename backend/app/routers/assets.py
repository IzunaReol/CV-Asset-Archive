import asyncio
import hashlib
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from typing import Any

from celery import Celery
from fastapi import APIRouter, Query, Request
from pymongo import DESCENDING

from ..annotation_overlay import parse_annotation_overlay
from ..audit import record_audit
from ..config import get_settings
from ..database import db
from ..dependencies import ReadUser, WriteUser
from ..errors import AppError
from ..schemas import (
    AssetRemarkUpdate,
    BatchAssetDeleteRequest,
    BatchTagRequest,
    UploadCompleteRequest,
    UploadInitRequest,
)
from ..storage import presigned_get, presigned_put, read_object, stat_object
from ..utils import new_id, now, public_document

router = APIRouter(prefix="/assets", tags=["assets"])
settings = get_settings()
celery_client = Celery(broker=settings.redis_url)
ALLOWED_SORTS = {"created_at", "updated_at", "name", "size"}
TAG_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,49}$")
SYSTEM_FILTER_FIELDS = {"remark", "created_at", "updated_at"}


def parse_filter_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AppError(400, "INVALID_DATE_FILTER", "时间筛选值格式不正确") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def asset_filter_clause(key: str, operator: str, value: str) -> dict[str, Any]:
    if key in {"created_at", "updated_at"}:
        if operator == "between":
            parts = value.split("|", 1)
            if len(parts) != 2:
                raise AppError(400, "INVALID_DATE_FILTER", "时间范围需要开始时间和结束时间")
            start, end = (parse_filter_datetime(item) for item in parts)
            if end <= start:
                raise AppError(400, "INVALID_DATE_RANGE", "结束时间必须晚于开始时间")
            condition: Any = {"$gte": start, "$lte": end}
            if key == "updated_at":
                return {
                    "$or": [
                        {"modified_at": condition},
                        {"modified_at": {"$exists": False}, "created_at": condition},
                    ]
                }
            return {key: condition}
        moment = parse_filter_datetime(value)
        operators = {"equals": moment, "lt": {"$lt": moment}, "gt": {"$gt": moment}}
        if operator not in operators:
            raise AppError(400, "INVALID_TAG_OPERATOR", "不支持的时间筛选条件")
        condition = operators[operator]
        if key == "updated_at":
            return {
                "$or": [
                    {"modified_at": condition},
                    {"modified_at": {"$exists": False}, "created_at": condition},
                ]
            }
        return {key: condition}

    field = "remark" if key == "remark" else f"tags.{key}"
    if operator == "equals":
        return {field: value}
    if operator == "notEquals" and key != "remark":
        return {field: {"$ne": value}}
    if operator == "contains":
        return {field: {"$regex": re.escape(value), "$options": "i"}}
    if operator == "notContains":
        return {field: {"$not": {"$regex": re.escape(value), "$options": "i"}}}
    raise AppError(400, "INVALID_TAG_OPERATOR", "不支持的筛选条件")


def updated_asset_tags(
    current: dict[str, Any],
    additions: dict[str, str | list[str]],
    removed_keys: list[str],
    removed_values: dict[str, list[str]],
) -> dict[str, Any]:
    tags = dict(current)
    for key, incoming in additions.items():
        existing_values = tags.get(key, [])
        existing = existing_values if isinstance(existing_values, list) else [existing_values]
        new_values = incoming if isinstance(incoming, list) else [incoming]
        tags[key] = list(dict.fromkeys([*filter(None, existing), *filter(None, new_values)]))
    for key, values_to_remove in removed_values.items():
        existing_values = tags.get(key, [])
        existing = existing_values if isinstance(existing_values, list) else [existing_values]
        remaining = [value for value in existing if value not in set(values_to_remove)]
        if remaining:
            tags[key] = remaining
        else:
            tags.pop(key, None)
    for key in removed_keys:
        tags.pop(key, None)
    return tags


@router.get("/stats")
async def asset_stats(user: ReadUser) -> dict[str, Any]:
    active = {"archived_at": None}
    untagged = {"$and": [active, {"$or": [{"tags": {}}, {"tags": {"$exists": False}}]}]}
    counts = {
        asset_type: await db.assets.count_documents({**active, "type": asset_type})
        for asset_type in (
            "image",
            "video",
            "annotation",
            "model",
            "archive",
            "image_annotation",
            "other",
        )
    }
    disk = await asyncio.to_thread(shutil.disk_usage, settings.storage_data_path)
    return {
        "total": await db.assets.count_documents(active),
        "untagged": await db.assets.count_documents(untagged),
        "by_type": counts,
        "storage": {"total": disk.total, "used": disk.used, "free": disk.free},
    }


def safe_filename(filename: str) -> str:
    name = PurePath(filename.replace("\\", "/")).name
    return re.sub(r"[^\w.()\- ]", "_", name, flags=re.UNICODE)[:255]


@router.post("/upload-sessions", status_code=201)
async def initialize_upload(body: UploadInitRequest, user: WriteUser) -> dict[str, Any]:
    if body.size > settings.max_upload_size_bytes:
        raise AppError(
            413,
            "FILE_TOO_LARGE",
            "文件超过当前 10 GB 上传限制",
            {"limit": settings.max_upload_size_bytes},
        )
    duplicate = None
    if body.sha256:
        duplicate = await db.assets.find_one(
            {"sha256": body.sha256.lower(), "size": body.size, "archived_at": None}
        )
    session_id = new_id()
    asset_id = new_id()
    project_segment = hashlib.sha256(body.project.encode()).hexdigest()[:16]
    object_key = (
        duplicate["object_key"]
        if duplicate
        else f"projects/{project_segment}/{body.asset_type.value}/{asset_id}/original"
    )
    document = {
        "id": session_id,
        "asset_id": asset_id,
        "filename": safe_filename(body.filename),
        "declared_size": body.size,
        "mime_type": body.mime_type,
        "asset_type": body.asset_type.value,
        "project": body.project,
        "sha256": body.sha256.lower() if body.sha256 else None,
        "object_key": object_key,
        "duplicate_asset_id": duplicate["id"] if duplicate else None,
        "owner_id": user["id"],
        "state": "reused" if duplicate else "pending",
        "created_at": now(),
        "expires_at": now() + timedelta(hours=24),
    }
    await db.upload_sessions.insert_one(document)
    return {
        "upload_session_id": session_id,
        "asset_id": asset_id,
        "upload_required": duplicate is None,
        "upload_url": None if duplicate else await asyncio.to_thread(presigned_put, object_key),
        "duplicate_asset_id": document["duplicate_asset_id"],
        "expires_at": document["expires_at"],
    }


@router.post("/upload-sessions/complete", status_code=201)
async def complete_upload(
    body: UploadCompleteRequest, request: Request, user: WriteUser
) -> dict[str, Any]:
    session = await db.upload_sessions.find_one(
        {"id": body.upload_session_id, "owner_id": user["id"]}
    )
    if session is None or session["expires_at"] <= now():
        raise AppError(404, "UPLOAD_SESSION_NOT_FOUND", "上传会话不存在或已过期")
    if session["state"] == "completed":
        asset = await db.assets.find_one({"id": session["asset_id"]})
        return public_document(asset) or {}
    if session["state"] != "reused":
        obj = await asyncio.to_thread(stat_object, session["object_key"])
        if obj is None:
            raise AppError(409, "UPLOAD_INCOMPLETE", "对象尚未上传完成")
        if obj.size != session["declared_size"]:
            raise AppError(409, "SIZE_MISMATCH", "实际文件大小与申报大小不一致")
    timestamp = now()
    asset = {
        "id": session["asset_id"],
        "name": session["filename"],
        "type": session["asset_type"],
        "object_key": session["object_key"],
        "sha256": session.get("sha256"),
        "size": session["declared_size"],
        "mime_type": session["mime_type"],
        "project": session["project"],
        "remark": "",
        "tags": body.tags,
        "status": "processing",
        "media": {},
        "created_by": user["id"],
        "created_at": timestamp,
        "updated_at": timestamp,
        "modified_at": timestamp,
        "archived_at": None,
        "reuses_asset_id": session.get("duplicate_asset_id"),
    }
    await db.assets.insert_one(asset)
    await db.upload_sessions.update_one({"id": session["id"]}, {"$set": {"state": "completed"}})
    job = {
        "id": new_id(),
        "type": "process_asset",
        "state": "queued",
        "progress": 0,
        "owner_id": user["id"],
        "input": {"asset_id": asset["id"]},
        "created_at": now(),
        "updated_at": now(),
    }
    await db.jobs.insert_one(job)
    try:
        await asyncio.to_thread(
            celery_client.send_task,
            "worker.tasks.process_asset",
            args=[job["id"], asset["id"]],
        )
    except Exception as exc:
        await db.jobs.update_one(
            {"id": job["id"]},
            {
                "$set": {
                    "state": "failed",
                    "error": {"code": "TASK_DISPATCH_FAILED", "message": str(exc)[:500]},
                    "updated_at": now(),
                }
            },
        )
    await record_audit(
        actor=user,
        action="asset.created",
        object_type="asset",
        object_id=asset["id"],
        request_id=request.state.request_id,
    )
    return public_document(asset) or {}


@router.get("")
async def list_assets(
    user: ReadUser,
    q: str = "",
    no_tags: bool = False,
    asset_type: list[str] = Query(default=[]),
    match: str = Query("all", pattern="^(all|any)$"),
    tag: list[str] = Query(default=[]),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort: str = "created_at",
    direction: str = Query("desc", pattern="^(asc|desc)$"),
) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = [{"archived_at": None}]
    invalid_types = set(asset_type) - {
        "image",
        "video",
        "annotation",
        "model",
        "archive",
        "image_annotation",
        "other",
    }
    if invalid_types:
        raise AppError(400, "INVALID_ASSET_TYPE", "包含不支持的素材类型")
    if asset_type:
        clauses.append({"type": {"$in": asset_type}})
    if q:
        keyword = re.escape(q.strip())
        searchable_tag_keys = await db.tag_definitions.distinct("key")
        clauses.append(
            {
                "$or": [
                    {"name": {"$regex": keyword, "$options": "i"}},
                    {"remark": {"$regex": keyword, "$options": "i"}},
                    *[
                        {f"tags.{key}": {"$regex": keyword, "$options": "i"}}
                        for key in searchable_tag_keys
                        if TAG_KEY_PATTERN.fullmatch(key)
                    ],
                ]
            }
        )
    if no_tags:
        clauses.append({"$or": [{"tags": {}}, {"tags": {"$exists": False}}]})
    parsed_tags: list[tuple[str, str, str]] = []
    for expression in tag:
        parts = expression.split(":", 2)
        if len(parts) != 3 or not TAG_KEY_PATTERN.fullmatch(parts[0]):
            raise AppError(400, "INVALID_TAG_FILTER", "标签筛选格式应为 标签:条件:值")
        parsed_tags.append((parts[0], parts[1], parts[2]))
    requested_keys = {item[0] for item in parsed_tags if item[0] not in SYSTEM_FILTER_FIELDS}
    if requested_keys:
        defined_keys = set(
            await db.tag_definitions.distinct("key", {"key": {"$in": list(requested_keys)}})
        )
        if missing_keys := requested_keys - defined_keys:
            raise AppError(
                400,
                "UNKNOWN_TAG_FILTER",
                "标签筛选包含未定义的标签",
                {"keys": sorted(missing_keys)},
            )
    tag_clauses = []
    for key, operator, value in parsed_tags:
        tag_clauses.append(asset_filter_clause(key, operator, value))
    if tag_clauses:
        clauses.append({"$and" if match == "all" else "$or": tag_clauses})
    mongo_filter = {"$and": clauses}
    sort_field = sort if sort in ALLOWED_SORTS else "created_at"
    order = DESCENDING if direction == "desc" else 1
    total = await db.assets.count_documents(mongo_filter)
    cursor = (
        db.assets.find(mongo_filter)
        .sort(sort_field, order)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = []
    async for item in cursor:
        result = public_document(item) or {}
        if item.get("preview_key"):
            result["preview_url"] = await asyncio.to_thread(presigned_get, item["preview_key"])
        items.append(result)
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@router.get("/{asset_id}")
async def get_asset(asset_id: str, user: ReadUser) -> dict[str, Any]:
    asset = await db.assets.find_one({"id": asset_id, "archived_at": None})
    if asset is None:
        raise AppError(404, "ASSET_NOT_FOUND", "素材不存在或已归档")
    result = public_document(asset) or {}
    preview_key = asset.get("preview_key")
    if preview_key:
        result["preview_url"] = await asyncio.to_thread(presigned_get, preview_key)
    elif asset.get("type") == "image":
        result["preview_url"] = await asyncio.to_thread(presigned_get, asset["object_key"])
    else:
        result["preview_url"] = None
    result["download_url"] = await asyncio.to_thread(
        presigned_get, asset["object_key"], 1, asset["name"]
    )
    result["relations"] = [
        public_document(item)
        async for item in db.relations.find(
            {"$or": [{"source_id": asset_id}, {"target_id": asset_id}], "status": "active"}
        ).limit(100)
    ]
    return result


@router.patch("/{asset_id}/remark")
async def update_asset_remark(
    asset_id: str, body: AssetRemarkUpdate, request: Request, user: WriteUser
) -> dict[str, Any]:
    remark = body.remark.strip()
    result = await db.assets.update_one(
        {"id": asset_id, "archived_at": None},
        {"$set": {"remark": remark, "updated_at": now(), "modified_at": now()}},
    )
    if not result.matched_count:
        raise AppError(404, "ASSET_NOT_FOUND", "素材不存在或已归档")
    await record_audit(
        actor=user,
        action="asset.remark_updated",
        object_type="asset",
        object_id=asset_id,
        request_id=request.state.request_id,
        changes={"remark": remark},
    )
    asset = await db.assets.find_one({"id": asset_id})
    return public_document(asset) or {}


@router.get("/{asset_id}/annotation-overlays")
async def annotation_overlays(asset_id: str, user: ReadUser) -> dict[str, Any]:
    image = await db.assets.find_one({"id": asset_id, "type": "image", "archived_at": None})
    if image is None:
        raise AppError(404, "IMAGE_ASSET_NOT_FOUND", "图片素材不存在或已归档")
    relation_cursor = db.relations.find(
        {
            "status": "active",
            "relation_type": "annotates",
            "$or": [{"source_id": asset_id}, {"target_id": asset_id}],
        }
    )
    sources = []
    async for relation in relation_cursor:
        annotation_id = (
            relation["target_id"] if relation["source_id"] == asset_id else relation["source_id"]
        )
        annotation = await db.assets.find_one(
            {"id": annotation_id, "type": "annotation", "archived_at": None}
        )
        if annotation is None:
            continue
        source = {
            "relation_id": relation["id"],
            "annotation_asset_id": annotation["id"],
            "annotation_name": annotation["name"],
            "format": annotation.get("media", {}).get("annotation_format"),
            "matched": False,
            "items": [],
        }
        try:
            content = await asyncio.to_thread(read_object, annotation["object_key"])
            source.update(
                parse_annotation_overlay(
                    content,
                    annotation["name"],
                    image["name"],
                    annotation.get("media", {}).get("classes"),
                )
            )
        except (ValueError, OSError, UnicodeError, KeyError) as exc:
            source["error"] = str(exc)
        sources.append(source)
    return {"asset_id": asset_id, "image_name": image["name"], "sources": sources}


@router.post("/batch-tags")
async def batch_tags(body: BatchTagRequest, request: Request, user: WriteUser) -> dict[str, Any]:
    succeeded, failed = [], []
    for asset_id in body.asset_ids:
        asset = await db.assets.find_one({"id": asset_id, "archived_at": None}, {"tags": 1})
        if asset:
            tags = updated_asset_tags(
                asset.get("tags") or {},
                body.set_tags,
                body.remove_tags,
                body.remove_tag_values,
            )
            await db.assets.update_one(
                {"id": asset_id},
                {"$set": {"tags": tags, "updated_at": now(), "modified_at": now()}},
            )
            succeeded.append(asset_id)
        else:
            failed.append({"id": asset_id, "code": "ASSET_NOT_FOUND"})
    await record_audit(
        actor=user,
        action="asset.batch_tags",
        object_type="asset",
        object_id="batch",
        request_id=request.state.request_id,
        changes={"asset_ids": succeeded},
    )
    return {"succeeded": succeeded, "failed": failed}


@router.post("/batch-delete")
async def batch_delete(
    body: BatchAssetDeleteRequest, request: Request, user: WriteUser
) -> dict[str, Any]:
    timestamp = now()
    result = await db.assets.update_many(
        {"id": {"$in": body.asset_ids}, "archived_at": None},
        {"$set": {"archived_at": timestamp, "updated_at": timestamp}},
    )
    existing = set(
        await db.assets.distinct("id", {"id": {"$in": body.asset_ids}, "archived_at": timestamp})
    )
    succeeded = [asset_id for asset_id in body.asset_ids if asset_id in existing]
    failed = [
        {"id": asset_id, "code": "ASSET_NOT_FOUND", "message": "素材不存在"}
        for asset_id in body.asset_ids
        if asset_id not in existing
    ]
    await record_audit(
        actor=user,
        action="asset.batch_deleted",
        object_type="asset",
        object_id="batch",
        request_id=request.state.request_id,
        changes={"asset_ids": succeeded, "count": result.modified_count},
    )
    return {"succeeded": succeeded, "failed": failed}


@router.post("/{asset_id}/archive")
async def archive_asset(asset_id: str, request: Request, user: WriteUser) -> dict[str, str]:
    result = await batch_delete(BatchAssetDeleteRequest(asset_ids=[asset_id]), request, user)
    if result["failed"]:
        failure = result["failed"][0]
        status_code = 409 if failure["code"] == "ASSET_PROCESSING" else 404
        raise AppError(status_code, failure["code"], failure["message"])
    return {"id": asset_id, "status": "archived"}


@router.get("/trash/items")
async def list_trash(
    user: ReadUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    query = {"archived_at": {"$ne": None}}
    total = await db.assets.count_documents(query)
    cursor = (
        db.assets.find(query)
        .sort("archived_at", DESCENDING)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = []
    async for item in cursor:
        result = public_document(item) or {}
        if item.get("preview_key"):
            result["preview_url"] = await asyncio.to_thread(presigned_get, item["preview_key"])
        elif item.get("type") == "image" and item.get("object_key"):
            result["preview_url"] = await asyncio.to_thread(presigned_get, item["object_key"])
        items.append(result)
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@router.post("/trash/restore")
async def restore_trash(
    body: BatchAssetDeleteRequest, request: Request, user: WriteUser
) -> dict[str, Any]:
    result = await db.assets.update_many(
        {"id": {"$in": body.asset_ids}, "archived_at": {"$ne": None}},
        {"$set": {"archived_at": None, "updated_at": now()}},
    )
    restored = set(
        await db.assets.distinct("id", {"id": {"$in": body.asset_ids}, "archived_at": None})
    )
    succeeded = [asset_id for asset_id in body.asset_ids if asset_id in restored]
    failed = [
        {"id": asset_id, "code": "ASSET_NOT_FOUND"}
        for asset_id in body.asset_ids
        if asset_id not in restored
    ]
    await record_audit(
        actor=user,
        action="asset.batch_restored",
        object_type="asset",
        object_id="batch",
        request_id=request.state.request_id,
        changes={"asset_ids": succeeded, "count": result.modified_count},
    )
    return {"succeeded": succeeded, "failed": failed}


@router.post("/trash/empty", status_code=202)
async def empty_trash(request: Request, user: WriteUser) -> dict[str, Any]:
    existing = await db.jobs.find_one(
        {"type": "trash_empty", "state": {"$in": ["queued", "running"]}}
    )
    if existing:
        return public_document(existing) or {}
    total = await db.assets.count_documents({"archived_at": {"$ne": None}})
    job = {
        "id": new_id(),
        "type": "trash_empty",
        "state": "queued",
        "progress": 0,
        "owner_id": user["id"],
        "input": {
            "asset_count": total,
            "actor_username": user["username"],
            "request_id": request.state.request_id,
        },
        "created_at": now(),
        "updated_at": now(),
    }
    await db.jobs.insert_one(job)
    try:
        await asyncio.to_thread(
            celery_client.send_task, "worker.tasks.empty_trash", args=[job["id"]]
        )
    except Exception as exc:
        await db.jobs.update_one(
            {"id": job["id"]},
            {
                "$set": {
                    "state": "failed",
                    "error": {"code": "TASK_DISPATCH_FAILED", "message": str(exc)[:500]},
                    "updated_at": now(),
                }
            },
        )
    return public_document(await db.jobs.find_one({"id": job["id"]})) or {}
