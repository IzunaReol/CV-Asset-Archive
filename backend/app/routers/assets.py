import asyncio
import hashlib
import json
import logging
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from typing import Any

from celery import Celery
from fastapi import APIRouter, Query, Request
from pymongo import ASCENDING, DESCENDING, UpdateOne

from ..annotation_overlay import parse_annotation_overlay
from ..asset_impact import usage_impact
from ..audit import record_audit
from ..config import get_settings
from ..database import db
from ..dependencies import (
    AssetDeleteUser,
    AssetEditUser,
    AssetReadUser,
    AssetUploadUser,
    TrashManageUser,
    TrashReadUser,
    ensure_action_access,
)
from ..errors import AppError
from ..schemas import (
    AssetRemarkUpdate,
    AssetSelectionCreate,
    BatchAssetDeleteRequest,
    BatchTagRequest,
    UploadBatchCompleteRequest,
    UploadBatchInitRequest,
    UploadCompleteRequest,
    UploadConflictCheckRequest,
    UploadInitRequest,
)
from ..storage import (
    compose_chunks,
    delete_chunks,
    delete_orphan_chunks,
    presigned_get,
    presigned_put,
    read_object,
    stat_object,
    uploaded_chunks,
)
from ..utils import new_id, now, public_document

router = APIRouter(prefix="/assets", tags=["assets"])
settings = get_settings()
celery_client = Celery(broker=settings.redis_url)
ALLOWED_SORTS = {"created_at", "updated_at", "name", "size"}
TAG_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,49}$")
SYSTEM_FILTER_FIELDS = {"remark", "created_at", "updated_at"}
CHUNK_SIZE = 64 * 1024 * 1024
CHUNK_THRESHOLD = 64 * 1024 * 1024
UPLOAD_BATCH_WINDOW = 12
logger = logging.getLogger("cv-archive.assets")


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
async def asset_stats(user: AssetReadUser) -> dict[str, Any]:
    active = {"archived_at": None}
    pipeline = [
        {"$match": active},
        {"$facet": {
            "by_type": [{"$group": {"_id": "$type", "count": {"$sum": 1}}}],
            "total": [{"$count": "count"}],
            "untagged": [
                {"$match": {"$or": [{"tags": {}}, {"tags": {"$exists": False}}]}},
                {"$count": "count"},
            ],
        }},
    ]
    rows = await (await db.assets.aggregate(pipeline)).to_list(length=1)
    summary = rows[0] if rows else {}
    counts = {item["_id"]: item["count"] for item in summary.get("by_type", [])}
    for asset_type in ("image", "video", "annotation", "model", "archive", "image_annotation", "other"):
        counts.setdefault(asset_type, 0)
    disk = await asyncio.to_thread(shutil.disk_usage, settings.storage_data_path)
    return {
        "total": (summary.get("total") or [{"count": 0}])[0]["count"],
        "untagged": (summary.get("untagged") or [{"count": 0}])[0]["count"],
        "by_type": counts,
        "storage": {"total": disk.total, "used": disk.used, "free": disk.free},
    }


def safe_filename(filename: str) -> str:
    name = PurePath(filename.replace("\\", "/")).name
    return re.sub(r"[^\w.()\- ]", "_", name, flags=re.UNICODE)[:255]


async def matching_name_assets(filename: str, asset_type: str) -> list[dict[str, Any]]:
    return await db.assets.find(
        {
            "normalized_name": filename.casefold(),
            "type": asset_type,
            "archived_at": None,
        },
        {
            "id": 1,
            "name": 1,
            "type": 1,
            "size": 1,
            "mime_type": 1,
            "status": 1,
            "tags": 1,
            "media": 1,
            "remark": 1,
            "created_at": 1,
            "modified_at": 1,
        },
    ).sort("created_at", DESCENDING).to_list(length=None)


@router.post("/upload-conflicts")
async def check_upload_conflicts(
    body: UploadConflictCheckRequest, user: AssetUploadUser
) -> dict[str, Any]:
    requested = [(index, safe_filename(item.filename), item.asset_type.value, item.size, item.sha256.lower() if item.sha256 else None) for index, item in enumerate(body.files)]
    names_by_type: dict[str, set[str]] = {}
    for _, filename, asset_type, _, _ in requested:
        names_by_type.setdefault(asset_type, set()).add(filename.casefold())
    clauses = [
        {"type": asset_type, "normalized_name": {"$in": sorted(names)}}
        for asset_type, names in names_by_type.items()
    ]
    content_clauses = [{"sha256": sha256, "size": size} for _, _, _, size, sha256 in requested if sha256]
    documents = await db.assets.find(
        {"archived_at": None, "$or": [*clauses, *content_clauses]},
        {"id": 1, "name": 1, "normalized_name": 1, "type": 1, "size": 1, "mime_type": 1,
         "status": 1, "tags": 1, "media": 1, "remark": 1, "sha256": 1, "created_at": 1, "modified_at": 1},
    ).sort("created_at", DESCENDING).to_list(length=None) if clauses or content_clauses else []
    matches_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for document in documents:
        key = (document["type"], document.get("normalized_name") or document.get("name", "").casefold())
        matches_by_key.setdefault(key, []).append(document)
    matches_by_hash: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for document in documents:
        if document.get("sha256"):
            matches_by_hash.setdefault((document["sha256"].lower(), document.get("size", 0)), []).append(document)
    asset_ids = [document["id"] for document in documents]
    related_ids: set[str] = set()
    if asset_ids:
        async for relation in db.relations.find(
            {"status": "active", "$or": [{"source_id": {"$in": asset_ids}}, {"target_id": {"$in": asset_ids}}]},
            {"source_id": 1, "target_id": 1},
        ):
            if relation.get("source_id") in asset_ids:
                related_ids.add(relation["source_id"])
            if relation.get("target_id") in asset_ids:
                related_ids.add(relation["target_id"])
    conflicts = []
    counts: dict[str, int] = {}
    for index, filename, asset_type, size, sha256 in requested:
        name_matches = matches_by_key.get((asset_type, filename.casefold()), [])
        content_matches = matches_by_hash.get((sha256, size), []) if sha256 else []
        matches = list({match["id"]: match for match in [*name_matches, *content_matches]}.values())
        if not matches:
            continue
        match_kind = "name_and_content" if name_matches and content_matches else "content" if content_matches else "name"
        conflict_items = [
            {**public_document(match), "has_active_relations": match["id"] in related_ids, "match_kind": match_kind}
            for match in matches
        ]
        conflicts.append({
            "index": index,
            "filename": filename,
            "asset_type": asset_type,
            "existing_count": len(matches),
            "existing_asset_id": matches[0]["id"],
            "overwrite_target_id": name_matches[0]["id"] if name_matches else None,
            "has_active_relations": any(match["id"] in related_ids for match in matches),
            "match_kind": match_kind,
            "items": conflict_items,
        })
        counts[asset_type] = counts.get(asset_type, 0) + 1
    return {
        "total": len(conflicts),
        "groups": [
            {
                "asset_type": asset_type,
                "count": count,
                "items": [
                    existing
                    for conflict in conflicts
                    if conflict["asset_type"] == asset_type
                    for existing in conflict["items"]
                ],
            }
            for asset_type, count in counts.items()
        ],
        "items": conflicts,
    }


@router.post("/upload-sessions", status_code=201)
async def initialize_upload(body: UploadInitRequest, user: AssetUploadUser) -> dict[str, Any]:
    if body.size > settings.max_upload_size_bytes:
        raise AppError(
            413,
            "FILE_TOO_LARGE",
            "文件超过当前上传限制",
            {"limit": settings.max_upload_size_bytes},
        )
    filename = safe_filename(body.filename)
    name_matches = await matching_name_assets(filename, body.asset_type.value)
    overwrite_asset = name_matches[0] if name_matches and body.name_conflict == "overwrite" else None
    if body.name_conflict == "overwrite":
        ensure_action_access(user, "asset_delete")
        if body.expected_overwrite_asset_id and (
            not overwrite_asset or overwrite_asset["id"] != body.expected_overwrite_asset_id
        ):
            raise AppError(409, "OVERWRITE_TARGET_CHANGED", "待覆盖素材已变化，请重新检查使用影响")
    if name_matches and body.name_conflict == "reject":
        raise AppError(409, "ASSET_NAME_CONFLICT", "素材库中已存在同名同类型文件")
    if name_matches and body.name_conflict == "rename":
        original = PurePath(filename)
        index = 1
        while True:
            candidate = f"{original.stem} ({index}){original.suffix}"
            if not await matching_name_assets(candidate, body.asset_type.value):
                filename = candidate
                break
            index += 1
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
    chunked = duplicate is None and body.size >= CHUNK_THRESHOLD
    document = {
        "id": session_id,
        "asset_id": asset_id,
        "filename": filename,
        "declared_size": body.size,
        "mime_type": body.mime_type,
        "asset_type": body.asset_type.value,
        "project": body.project,
        "sha256": body.sha256.lower() if body.sha256 else None,
        "object_key": object_key,
        "duplicate_asset_id": duplicate["id"] if duplicate else None,
        "overwrite_asset_id": overwrite_asset["id"] if overwrite_asset else None,
        "processing_job_id": new_id(),
        "owner_id": user["id"],
        "state": "reused" if duplicate else "pending",
        "transfer_mode": "chunks" if chunked else "single",
        "chunk_size": CHUNK_SIZE if chunked else None,
        "chunk_count": (body.size + CHUNK_SIZE - 1) // CHUNK_SIZE if chunked else None,
        "created_at": now(),
        "expires_at": now() + timedelta(hours=24),
    }
    upload_url = (
        None
        if duplicate or chunked
        else await asyncio.to_thread(presigned_put, object_key)
    )
    await db.upload_sessions.insert_one(document)
    return {
        "upload_session_id": session_id,
        "asset_id": asset_id,
        "upload_required": duplicate is None,
        "upload_url": upload_url,
        "transfer_mode": document["transfer_mode"],
        "chunk_size": document["chunk_size"],
        "chunk_count": document["chunk_count"],
        "duplicate_asset_id": document["duplicate_asset_id"],
        "overwrite_asset_id": document["overwrite_asset_id"],
        "expires_at": document["expires_at"],
    }


def chunk_prefix(session_id: str) -> str:
    return f"uploads/{session_id}/"


async def cleanup_expired_upload_chunks() -> int:
    active_session_ids = set(await db.upload_sessions.distinct("id", {"expires_at": {"$gt": now()}}))
    return await asyncio.to_thread(
        delete_orphan_chunks, active_session_ids, now() - timedelta(hours=24)
    )


@router.get("/upload-sessions")
async def list_resumable_upload_sessions(user: AssetUploadUser) -> dict[str, Any]:
    cursor = db.upload_sessions.find({
        "owner_id": user["id"],
        "expires_at": {"$gt": now()},
        "state": {"$in": ["pending", "reused"]},
        "transfer_mode": "chunks",
    }).sort("created_at", -1).limit(200)
    sessions = [item async for item in cursor]

    async def summarize(session: dict[str, Any]) -> dict[str, Any]:
        existing = await asyncio.to_thread(uploaded_chunks, chunk_prefix(session["id"]))
        chunk_size = int(session.get("chunk_size") or CHUNK_SIZE)
        chunk_count = int(session.get("chunk_count") or 0)
        uploaded_parts = sum(
            1 for number in range(chunk_count)
            if existing.get(number) == min(chunk_size, session["declared_size"] - number * chunk_size)
        )
        return {
            "upload_session_id": session["id"],
            "filename": session["filename"],
            "size": session["declared_size"],
            "asset_type": session["asset_type"],
            "uploaded_parts": uploaded_parts,
            "chunk_count": chunk_count,
            "progress": round(uploaded_parts * 100 / chunk_count) if chunk_count else 0,
            "created_at": session["created_at"],
            "expires_at": session["expires_at"],
        }

    return {"items": await asyncio.gather(*(summarize(item) for item in sessions))}


@router.get("/upload-sessions/{session_id}")
async def upload_session_status(session_id: str, user: AssetUploadUser) -> dict[str, Any]:
    session = await db.upload_sessions.find_one({"id": session_id, "owner_id": user["id"]})
    if session is None or session["expires_at"] <= now() or session["state"] not in {"pending", "reused"}:
        raise AppError(404, "UPLOAD_SESSION_NOT_FOUND", "上传会话不存在或已过期")
    result = {
        "upload_session_id": session_id,
        "filename": session["filename"],
        "size": session["declared_size"],
        "asset_type": session["asset_type"],
        "transfer_mode": session.get("transfer_mode", "single"),
        "upload_required": session["state"] != "reused",
        "chunk_size": session.get("chunk_size"),
        "chunk_count": session.get("chunk_count"),
    }
    if result["transfer_mode"] == "chunks":
        prefix = chunk_prefix(session_id)
        existing = await asyncio.to_thread(uploaded_chunks, prefix)
        count = session["chunk_count"]
        size = session["chunk_size"]
        result["uploaded_parts"] = [number for number in range(count) if existing.get(number) == min(size, session["declared_size"] - number * size)]
        result["upload_urls"] = {
            str(number): await asyncio.to_thread(presigned_put, f"{prefix}{number:05d}")
            for number in range(count) if number not in result["uploaded_parts"]
        }
    return result


@router.delete("/upload-sessions/{session_id}", status_code=204)
async def cancel_upload_session(session_id: str, user: AssetUploadUser) -> None:
    session = await db.upload_sessions.find_one({"id": session_id, "owner_id": user["id"]})
    if session is None or session["state"] == "completed":
        raise AppError(404, "UPLOAD_SESSION_NOT_FOUND", "上传会话不存在或已完成")
    if session.get("transfer_mode") == "chunks":
        await asyncio.to_thread(delete_chunks, chunk_prefix(session_id))
    await db.upload_sessions.delete_one({"id": session_id, "owner_id": user["id"]})


@router.post("/upload-sessions/batch", status_code=201)
async def initialize_upload_batch(body: UploadBatchInitRequest, user: AssetUploadUser) -> dict[str, Any]:
    async def initialize_one(index: int, item: UploadInitRequest) -> dict[str, Any]:
        try:
            return {"index": index, "session": await initialize_upload(item, user)}
        except AppError as exc:
            return {"index": index, "error": {"code": exc.code, "message": exc.message}}
        except Exception:
            logger.exception("upload batch initialization failed", extra={"upload_index": index})
            return {"index": index, "error": {"code": "UPLOAD_INIT_FAILED", "message": "创建上传任务失败"}}

    return {"items": await run_upload_windows(body.files, initialize_one)}


@router.post("/upload-sessions/complete", status_code=201)
async def complete_upload(
    body: UploadCompleteRequest, request: Request, user: AssetUploadUser
) -> dict[str, Any]:
    session = await db.upload_sessions.find_one(
        {"id": body.upload_session_id, "owner_id": user["id"]}
    )
    if session is None or session["expires_at"] <= now():
        raise AppError(404, "UPLOAD_SESSION_NOT_FOUND", "上传会话不存在或已过期")
    if session.get("overwrite_asset_id"):
        ensure_action_access(user, "asset_delete")
    if session["state"] == "completed":
        asset = await db.assets.find_one(
            {"id": session.get("overwrite_asset_id") or session["asset_id"]}
        )
        return public_document(asset) or {}
    if session["state"] != "reused":
        if session.get("transfer_mode") == "chunks":
            obj = await asyncio.to_thread(stat_object, session["object_key"])
            if obj is None or obj.size != session["declared_size"]:
                prefix = chunk_prefix(session["id"])
                parts = await asyncio.to_thread(uploaded_chunks, prefix)
                count = session["chunk_count"]
                size = session["chunk_size"]
                if any(parts.get(number) != min(size, session["declared_size"] - number * size) for number in range(count)):
                    raise AppError(409, "UPLOAD_INCOMPLETE", "文件分片尚未上传完成")
                await asyncio.to_thread(
                    compose_chunks,
                    session["object_key"],
                    [f"{prefix}{number:05d}" for number in range(count)],
                )
        obj = await asyncio.to_thread(stat_object, session["object_key"])
        if obj is None:
            raise AppError(409, "UPLOAD_INCOMPLETE", "对象尚未上传完成")
        if obj.size != session["declared_size"]:
            raise AppError(409, "SIZE_MISMATCH", "实际文件大小与申报大小不一致")
    timestamp = now()
    overwrite_asset_id = session.get("overwrite_asset_id")
    asset_id = overwrite_asset_id or session["asset_id"]
    previous_object_key = session.get("previous_object_key")
    asset = {
        "id": asset_id,
        "name": session["filename"],
        "normalized_name": session["filename"].casefold(),
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
    if overwrite_asset_id:
        existing = await db.assets.find_one({"id": overwrite_asset_id, "archived_at": None})
        if existing is None:
            raise AppError(409, "OVERWRITE_TARGET_NOT_FOUND", "要覆盖的原文件已不存在")
        if previous_object_key is None:
            previous_object_key = existing.get("object_key")
            await db.upload_sessions.update_one(
                {"id": session["id"]},
                {"$set": {"previous_object_key": previous_object_key}},
            )
        asset["created_at"] = existing.get("created_at", timestamp)
        asset["tags"] = body.tags or existing.get("tags", {})
        asset["remark"] = existing.get("remark", "")
        await db.assets.replace_one({"id": overwrite_asset_id}, asset)
    else:
        await db.assets.replace_one({"id": asset_id}, asset, upsert=True)
    job_id = session.get("processing_job_id") or f"upload-{session['id']}"
    job = {
        "id": job_id,
        "type": "process_asset",
        "name": f"素材处理：{asset['name']}",
        "state": "queued",
        "progress": 0,
        "owner_id": user["id"],
        "input": {
            "asset_id": asset["id"],
            "previous_object_key": previous_object_key,
        },
        "created_at": now(),
        "updated_at": now(),
    }
    await db.jobs.update_one({"id": job_id}, {"$setOnInsert": job}, upsert=True)
    await db.upload_sessions.update_one(
        {"id": session["id"]},
        {"$set": {"state": "completed", "processing_job_id": job_id}},
    )
    try:
        await asyncio.to_thread(
            celery_client.send_task,
            "worker.tasks.process_asset",
            args=[job["id"], asset["id"]],
        )
        try:
            await db.jobs.update_one(
                {"id": job_id},
                {"$set": {"dispatched_at": now(), "updated_at": now()}},
            )
        except Exception:
            logger.warning("upload job dispatch marker update failed", extra={"job_id": job_id})
    except Exception as exc:
        await db.jobs.update_one(
            {"id": job["id"]},
            {
                "$set": {
                    "dispatch_error": f"{type(exc).__name__}: {str(exc)[:300]}",
                    "updated_at": now(),
                }
            },
        )
    if session.get("transfer_mode") == "chunks":
        try:
            await asyncio.to_thread(delete_chunks, chunk_prefix(session["id"]))
        except Exception:
            logger.warning(
                "completed upload chunk cleanup failed",
                extra={"upload_session_id": session["id"]},
            )
    await record_audit(
        actor=user,
        action="asset.overwritten" if overwrite_asset_id else "asset.created",
        object_type="asset",
        object_id=asset["id"],
        request_id=request.state.request_id,
        changes={
            "upload_session_id": session["id"],
            "filename": asset["name"],
            "size": asset["size"],
            "mime_type": asset["mime_type"],
            "previous_object_key": previous_object_key,
            "new_object_key": asset["object_key"],
            "relations_preserved": bool(overwrite_asset_id),
        },
    )
    return public_document(asset) or {}


@router.get("/{asset_id}/history")
async def asset_operation_history(
    asset_id: str, user: AssetReadUser,
    page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=200),
) -> dict[str, Any]:
    if await db.assets.find_one({"id": asset_id}, {"id": 1}) is None:
        raise AppError(404, "ASSET_NOT_FOUND", "素材不存在")
    query = {"object_type": "asset", "object_id": asset_id}
    cursor = db.audit_logs.find(query).sort(
        [("created_at", DESCENDING), ("id", DESCENDING)]
    ).skip((page - 1) * page_size).limit(page_size)
    return {"items": [public_document(item) async for item in cursor],
            "total": await db.audit_logs.count_documents(query), "page": page, "page_size": page_size}


async def run_upload_windows(items: list[Any], worker: Any) -> list[dict[str, Any]]:
    """Run only one small upload window at a time while preserving response order."""
    results: list[dict[str, Any]] = []
    for start in range(0, len(items), UPLOAD_BATCH_WINDOW):
        window = items[start : start + UPLOAD_BATCH_WINDOW]
        results.extend(
            await asyncio.gather(*(
                worker(start + offset, item) for offset, item in enumerate(window)
            ))
        )
    return results


@router.post("/upload-sessions/complete-batch", status_code=201)
async def complete_upload_batch(
    body: UploadBatchCompleteRequest, request: Request, user: AssetUploadUser
) -> dict[str, Any]:
    async def complete_one(index: int, session_id: str) -> dict[str, Any]:
        try:
            asset = await complete_upload(
                UploadCompleteRequest(upload_session_id=session_id, tags=body.tags),
                request,
                user,
            )
            return {"index": index, "asset": asset}
        except AppError as exc:
            return {"index": index, "error": {"code": exc.code, "message": exc.message}}
        except Exception:
            logger.exception("upload batch completion failed", extra={"upload_index": index})
            return {"index": index, "error": {"code": "UPLOAD_COMPLETE_FAILED", "message": "完成上传失败，请稍后重试"}}

    return {"items": await run_upload_windows(body.upload_session_ids, complete_one)}


async def asset_query(q: str, no_tags: bool, asset_type: list[str], match: str, tag: list[str]) -> dict[str, Any]:
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
    return {"$and": clauses}


@router.post("/selection-sets", status_code=201)
async def create_asset_selection(body: AssetSelectionCreate, user: AssetReadUser) -> dict[str, Any]:
    query = await asset_query(body.q, body.no_tags, [item.value for item in body.asset_type], body.match, body.tag)
    ids = [item["id"] async for item in db.assets.find(query, {"id": 1}).limit(100001)]
    if len(ids) > 100000:
        raise AppError(413, "SELECTION_TOO_LARGE", "当前筛选结果超过 10 万项，请缩小范围")
    selection_id = new_id()
    await db.asset_selection_sets.insert_one({
        "id": selection_id, "owner_id": user["id"], "asset_ids": ids,
        "created_at": now(), "expires_at": now() + timedelta(hours=2),
    })
    return {"selection_id": selection_id, "total": len(ids), "expires_in_seconds": 7200}


async def resolve_selection_ids(
    user: dict[str, Any], asset_ids: list[str], selection_id: str | None, excluded_ids: list[str]
) -> list[str]:
    if selection_id:
        if asset_ids:
            raise AppError(400, "SELECTION_CONFLICT", "不能同时提交素材和选择集")
        selection = await db.asset_selection_sets.find_one({
            "id": selection_id, "owner_id": user["id"], "expires_at": {"$gt": now()},
        })
        if selection is None:
            raise AppError(404, "SELECTION_EXPIRED", "选择已过期，请重新选择素材")
        excluded = set(excluded_ids)
        return [item for item in selection["asset_ids"] if item not in excluded]
    if excluded_ids:
        raise AppError(400, "SELECTION_CONFLICT", "排除项需要选择集")
    return list(dict.fromkeys(asset_ids))


@router.get("")
async def list_assets(
    user: AssetReadUser,
    q: str = "",
    no_tags: bool = False,
    asset_type: list[str] = Query(default=[]),
    match: str = Query("all", pattern="^(all|any)$"),
    tag: list[str] = Query(default=[]),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort: str = "created_at",
    direction: str = Query("desc", pattern="^(asc|desc)$"),
    after: str | None = None,
) -> dict[str, Any]:
    mongo_filter = await asset_query(q, no_tags, asset_type, match, tag)
    sort_field = sort if sort in ALLOWED_SORTS else "created_at"
    order = DESCENDING if direction == "desc" else 1
    total = await db.assets.count_documents(mongo_filter)
    if after:
        previous = await db.assets.find_one({"id": after}, {"id": 1, sort_field: 1})
        if previous is None or sort_field not in previous:
            raise AppError(400, "CURSOR_INVALID", "分页位置已失效，请重新加载")
        comparison = "$lt" if direction == "desc" else "$gt"
        mongo_filter = {"$and": [mongo_filter, {"$or": [
            {sort_field: {comparison: previous[sort_field]}},
            {sort_field: previous[sort_field], "id": {"$gt": previous["id"]}},
        ]}]}
    cursor = (
        db.assets.find(mongo_filter)
        .sort([(sort_field, order), ("id", ASCENDING)])
        .skip(0 if after else (page - 1) * page_size)
        .limit(page_size)
    )
    items = []
    async for item in cursor:
        result = public_document(item) or {}
        if item.get("preview_key"):
            result["preview_url"] = await asyncio.to_thread(presigned_get, item["preview_key"])
        items.append(result)
    image_ids = [item["id"] for item in items if item.get("type") == "image"]
    annotated_ids = set(await db.relations.distinct("target_id", {
        "target_id": {"$in": image_ids}, "relation_type": "annotates", "status": "active",
    })) if image_ids else set()
    for item in items:
        item["has_annotation"] = item["id"] in annotated_ids
    return {"items": items, "page": page, "page_size": page_size, "total": total,
            "next_cursor": items[-1]["id"] if len(items) == page_size else None}


@router.post("/usage-impact")
async def preview_usage_impact(
    body: BatchAssetDeleteRequest, user: AssetReadUser
) -> dict[str, Any]:
    ids = await resolve_selection_ids(user, body.asset_ids, body.selection_id, body.excluded_ids)
    if not ids:
        raise AppError(400, "SELECTION_EMPTY", "没有可查询的素材")
    return await usage_impact(ids)


@router.get("/{asset_id}")
async def get_asset(asset_id: str, user: AssetReadUser) -> dict[str, Any]:
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
        )
    ]
    current_dataset_ids = await db.dataset_memberships.distinct("dataset_id", {"asset_id": asset_id})
    version_rows = await db.dataset_version_memberships.find(
        {"asset_id": asset_id}, {"version_id": 1}
    ).to_list(length=1000)
    model_version_ids = await db.relations.distinct(
        "target_id",
        {"source_id": asset_id, "relation_type": "trained_on", "status": "active"},
    )
    version_ids = list({item["version_id"] for item in version_rows} | set(model_version_ids))
    versions = (
        await db.dataset_versions.find({"id": {"$in": version_ids}}).to_list(length=len(version_ids))
        if version_ids
        else []
    )
    valid_version_ids = {item["id"] for item in versions}
    result["relations"] = [item for item in result["relations"] if item.get("relation_type") != "trained_on" or item.get("target_id") in valid_version_ids]
    if asset.get("type") == "model":
        result["relations"] = [item for item in result["relations"] if item.get("relation_type") == "trained_on" and item.get("target_id") in valid_version_ids]
    dataset_ids = list(set(current_dataset_ids) | {item["dataset_id"] for item in versions})
    datasets = {
        item["id"]: item
        for item in (
            await db.datasets.find({"id": {"$in": dataset_ids}, "deleted_at": None}).to_list(
                length=len(dataset_ids)
            )
            if dataset_ids
            else []
        )
    }
    versions_by_dataset: dict[str, list[str]] = {}
    for version in versions:
        if version["dataset_id"] in datasets:
            versions_by_dataset.setdefault(version["dataset_id"], []).append(version["version"])
    result["datasets"] = [
        {
            "id": dataset_id,
            "name": dataset["name"],
            "in_current_dataset": dataset_id in current_dataset_ids,
            "versions": versions_by_dataset.get(dataset_id, []),
        }
        for dataset_id, dataset in datasets.items()
    ]
    return result


@router.patch("/{asset_id}/remark")
async def update_asset_remark(
    asset_id: str, body: AssetRemarkUpdate, request: Request, user: AssetEditUser
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
async def annotation_overlays(asset_id: str, user: AssetReadUser) -> dict[str, Any]:
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
async def batch_tags(body: BatchTagRequest, request: Request, user: AssetEditUser) -> dict[str, Any]:
    ids = await resolve_selection_ids(user, body.asset_ids, body.selection_id, body.excluded_ids)
    if not ids:
        raise AppError(400, "SELECTION_EMPTY", "没有可操作的素材")
    succeeded, failed, details = [], [], []
    timestamp = now()
    for offset in range(0, len(ids), 1000):
        chunk = ids[offset:offset + 1000]
        assets = {item["id"]: item async for item in db.assets.find(
            {"id": {"$in": chunk}, "archived_at": None}, {"id": 1, "name": 1, "tags": 1}
        )}
        operations = []
        for asset_id in chunk:
            asset = assets.get(asset_id)
            if asset is None:
                failed.append({"id": asset_id, "code": "ASSET_NOT_FOUND"})
                if len(details) < 1000:
                    details.append({"id": asset_id, "name": asset_id, "status": "failed", "message": "素材不存在"})
                continue
            tags = updated_asset_tags(asset.get("tags") or {}, body.set_tags, body.remove_tags, body.remove_tag_values)
            operations.append(UpdateOne(
                {"id": asset_id, "archived_at": None},
                {"$set": {"tags": tags, "updated_at": timestamp, "modified_at": timestamp}},
            ))
            succeeded.append(asset_id)
            if len(details) < 1000:
                details.append({"id": asset_id, "name": asset.get("name", asset_id), "status": "succeeded", "message": "标签已更新"})
        if operations:
            await db.assets.bulk_write(operations, ordered=False)
    await record_audit(
        actor=user,
        action="asset.batch_tags",
        object_type="asset",
        object_id="batch",
        request_id=request.state.request_id,
        changes={"asset_ids": succeeded[:1000], "count": len(succeeded), "selection_id": body.selection_id},
    )
    return {"succeeded": succeeded if not body.selection_id else [],
            "succeeded_count": len(succeeded), "failed": failed[:100], "failed_count": len(failed),
            "details": details, "details_truncated": len(succeeded) + len(failed) > len(details)}


@router.post("/batch-delete")
async def batch_delete(
    body: BatchAssetDeleteRequest, request: Request, user: AssetDeleteUser
) -> dict[str, Any]:
    requested_ids = await resolve_selection_ids(user, body.asset_ids, body.selection_id, body.excluded_ids)
    if not requested_ids:
        raise AppError(400, "SELECTION_EMPTY", "没有可删除的素材")
    if not body.confirm_linked:
        linked_query = {"asset_id": {"$in": requested_ids}}
        relation_query = {"status": "active", "$or": [
            {"source_id": {"$in": requested_ids}}, {"target_id": {"$in": requested_ids}},
        ]}
        if (await db.dataset_memberships.find_one(linked_query)
                or await db.dataset_version_memberships.find_one(linked_query)
                or await db.relations.find_one(relation_query)):
            raise AppError(409, "ASSET_RELATIONS_CONFIRM_REQUIRED", "素材关联关系已变化，请重新查看使用影响并确认")
    if len(requested_ids) > 5000:
        succeeded_count = failed_count = 0
        failures: list[dict[str, str]] = []
        details: list[dict[str, str]] = []
        details_truncated = False
        for offset in range(0, len(requested_ids), 5000):
            result = await batch_delete(
                BatchAssetDeleteRequest(asset_ids=requested_ids[offset:offset + 5000],
                                        confirm_linked=body.confirm_linked), request, user
            )
            succeeded_count += len(result["succeeded"])
            failed_count += len(result["failed"])
            failures.extend(result["failed"][:max(0, 100 - len(failures))])
            details.extend(result.get("details", [])[:max(0, 1000 - len(details))])
            details_truncated = details_truncated or result.get("details_truncated", False)
        return {"succeeded": [], "succeeded_count": succeeded_count,
                "failed": failures, "failed_count": failed_count, "details": details,
                "details_truncated": details_truncated or succeeded_count + failed_count > len(details)}
    asset_names = {item["id"]: item.get("name", item["id"]) async for item in db.assets.find(
        {"id": {"$in": requested_ids}}, {"id": 1, "name": 1}
    )}
    timestamp = now()
    result = await db.assets.update_many(
        {"id": {"$in": requested_ids}, "archived_at": None},
        {"$set": {"archived_at": timestamp, "updated_at": timestamp}},
    )
    existing = set(
        await db.assets.distinct("id", {"id": {"$in": requested_ids}, "archived_at": timestamp})
    )
    succeeded = [asset_id for asset_id in requested_ids if asset_id in existing]
    failed = [
        {"id": asset_id, "code": "ASSET_NOT_FOUND", "message": "素材不存在"}
        for asset_id in requested_ids
        if asset_id not in existing
    ]
    current_members_deleted = version_members_deleted = relations_deleted = 0
    if succeeded:
        succeeded_query = {"asset_id": {"$in": succeeded}}
        dataset_ids = await db.dataset_memberships.distinct("dataset_id", succeeded_query)
        version_ids = await db.dataset_version_memberships.distinct("version_id", succeeded_query)
        current_members_deleted = (await db.dataset_memberships.delete_many(succeeded_query)).deleted_count
        version_members_deleted = (await db.dataset_version_memberships.delete_many(succeeded_query)).deleted_count
        relations_deleted = (await db.relations.delete_many({"$or": [
            {"source_id": {"$in": succeeded}}, {"target_id": {"$in": succeeded}},
        ]})).deleted_count
        if version_ids:
            versions = await db.dataset_versions.find(
                {"id": {"$in": version_ids}}, {"id": 1, "dataset_id": 1}
            ).to_list(length=len(version_ids))
            dataset_ids.extend(version["dataset_id"] for version in versions)
            for version in versions:
                members = await db.dataset_version_memberships.find(
                    {"version_id": version["id"]}, {"asset_id": 1, "snapshot": 1}
                ).sort("asset_id", ASCENDING).to_list(length=None)
                content = [{"asset_id": member["asset_id"], "snapshot": member["snapshot"]}
                           for member in members]
                digest = hashlib.sha256(json.dumps(
                    content, ensure_ascii=False, sort_keys=True, default=str,
                ).encode()).hexdigest()
                await db.dataset_versions.update_one({"id": version["id"]}, {"$set": {
                    "member_count": len(members),
                    "total_size": sum(int(member["snapshot"].get("size") or 0) for member in members),
                    "content_digest": digest,
                }})
        if dataset_ids:
            await db.datasets.update_many(
                {"id": {"$in": list(set(dataset_ids))}}, {"$set": {"updated_at": timestamp}},
            )
    await record_audit(
        actor=user,
        action="asset.batch_deleted",
        object_type="asset",
        object_id="batch",
        request_id=request.state.request_id,
        changes={"asset_ids": succeeded, "count": result.modified_count,
                 "current_members_deleted": current_members_deleted,
                 "version_members_deleted": version_members_deleted,
                 "relations_deleted": relations_deleted},
    )
    details = [
        {"id": asset_id, "name": asset_names.get(asset_id, asset_id), "status": "succeeded", "message": "已移入回收站"}
        for asset_id in succeeded
    ] + [
        {"id": item["id"], "name": asset_names.get(item["id"], item["id"]), "status": "failed", "message": item["message"]}
        for item in failed
    ]
    details = details[:1000]
    return {"succeeded": succeeded if not body.selection_id else [],
            "succeeded_count": len(succeeded),
            "failed": failed if not body.selection_id else failed[:100],
            "failed_count": len(failed), "details": details,
            "details_truncated": len(succeeded) + len(failed) > len(details)}


@router.post("/{asset_id}/archive")
async def archive_asset(
    asset_id: str, request: Request, user: AssetDeleteUser, confirm_linked: bool = False
) -> dict[str, str]:
    result = await batch_delete(
        BatchAssetDeleteRequest(asset_ids=[asset_id], confirm_linked=confirm_linked), request, user
    )
    if result["failed"]:
        failure = result["failed"][0]
        raise AppError(404, failure["code"], failure["message"])
    return {"id": asset_id, "status": "archived"}


@router.get("/trash/items")
async def list_trash(
    user: TrashReadUser,
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
    body: BatchAssetDeleteRequest, request: Request, user: TrashManageUser
) -> dict[str, Any]:
    asset_names = {item["id"]: item.get("name", item["id"]) async for item in db.assets.find(
        {"id": {"$in": body.asset_ids}}, {"id": 1, "name": 1}
    )}
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
    return {
        "succeeded": succeeded,
        "succeeded_count": len(succeeded),
        "failed": failed,
        "failed_count": len(failed),
        "details": [
            {"id": asset_id, "name": asset_names.get(asset_id, asset_id), "status": "succeeded", "message": "还原成功"}
            for asset_id in succeeded
        ] + [
            {"id": item["id"], "name": asset_names.get(item["id"], item["id"]), "status": "failed", "message": "素材不存在或已被还原"}
            for item in failed
        ],
        "details_truncated": False,
    }


@router.post("/trash/empty", status_code=202)
async def empty_trash(request: Request, user: TrashManageUser) -> dict[str, Any]:
    existing = await db.jobs.find_one(
        {"type": "trash_empty", "state": {"$in": ["queued", "running"]}}
    )
    if existing:
        return public_document(existing) or {}
    total = await db.assets.count_documents({"archived_at": {"$ne": None}})
    job = {
        "id": new_id(),
        "type": "trash_empty",
        "name": "清空回收站",
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
