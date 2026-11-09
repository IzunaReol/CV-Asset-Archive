import asyncio
import hashlib
import json
import re
from contextlib import suppress
from functools import wraps
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, Field
from celery import Celery
from fastapi import APIRouter, Query, Request
from pymongo import ASCENDING, DESCENDING, UpdateOne

from ..audit import record_audit
from ..config import get_settings
from ..database import db
from ..dataset_versioning import (
    DATASET_COMPARE_DETAIL_LIMIT,
    compare_version_memberships,
    cursor_batches,
)
from ..dataset_splits import SPLITS, SPLIT_LABELS, allocation_preview, split_of
from ..dependencies import (
    DatasetCreateEditUser, DatasetDeleteUser, DatasetExportUser, DatasetMembersUser,
    DatasetModelUser, DatasetReadUser, DatasetVersionPublishUser,
    DatasetVersionRestoreUser,
)
from ..errors import AppError
from ..schemas import (
    DatasetCreate,
    DatasetExportRequest,
    DatasetMembersRequest,
    DatasetModelLinkRequest,
    DatasetModelRemarkUpdate,
    DatasetPublishRequest,
    DatasetSplitUpdate,
    DatasetAutoSplitRequest,
    DatasetRestoreRequest,
    DatasetUpdate,
)
from ..storage import presigned_get
from ..utils import new_id, now, public_document
from .assets import asset_filter_clause, resolve_selection_ids

router = APIRouter(prefix="/datasets", tags=["datasets"])
settings = get_settings()
celery_client = Celery(broker=settings.redis_url)


def serialize_dataset_write(function):
    @wraps(function)
    async def guarded(dataset_id, *args, **kwargs):
        token = new_id()
        acquired = await db.datasets.update_one(
            {"id": dataset_id, "deleted_at": None, "$or": [
                {"write_token": None}, {"write_token_expires_at": {"$lte": now()}},
            ]},
            {"$set": {"write_token": token, "write_token_expires_at": now() + timedelta(minutes=5)}},
        )
        if not acquired.modified_count:
            await _get_dataset(dataset_id)
            raise AppError(409, "DATASET_BUSY", "数据集正在处理，请稍后重试")
        async def renew_lease():
            while True:
                await asyncio.sleep(30)
                result = await db.datasets.update_one(
                    {"id": dataset_id, "write_token": token},
                    {"$set": {"write_token_expires_at": now() + timedelta(minutes=5)}},
                )
                if not result.matched_count:
                    return

        heartbeat = asyncio.create_task(renew_lease())
        try:
            await _resume_pending_restore(dataset_id)
            return await function(dataset_id, *args, **kwargs)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            await db.datasets.update_one(
                {"id": dataset_id, "write_token": token},
                {"$unset": {"write_token": "", "write_token_expires_at": ""}},
            )
    return guarded


async def _restore_memberships_from_version(dataset_id: str, version_id: str, actor_id: str) -> int:
    _, valid_labels = _classification(await _get_dataset(dataset_id))
    await db.dataset_memberships.delete_many({"dataset_id": dataset_id})
    restored = 0
    cursor = db.dataset_version_memberships.find({"version_id": version_id}).sort(
        "asset_id", ASCENDING
    )
    async for members in cursor_batches(cursor):
        workset_members = [
            {
                "id": new_id(), "dataset_id": dataset_id, "asset_id": item["asset_id"],
                "split": (split_of(item["snapshot"]) if split_of(item["snapshot"]) in valid_labels else "unassigned") if item["snapshot"].get("type") == "image" else None,
                "created_by": actor_id, "created_at": now(),
            }
            for item in members if item["snapshot"].get("type") != "annotation"
        ]
        if workset_members:
            await db.dataset_memberships.insert_many(workset_members)
        restored += len(members)
    await sync_annotation_memberships(dataset_id, actor_id)
    await db.datasets.update_one({"id": dataset_id}, {"$set": {"updated_at": now()}})
    return restored


async def _backup_dataset_memberships(dataset_id: str, restore_id: str) -> None:
    expires_at = now() + timedelta(days=1)
    cursor = db.dataset_memberships.find({"dataset_id": dataset_id}).sort("asset_id", ASCENDING)
    async for members in cursor_batches(cursor):
        await db.dataset_restore_backups.insert_many([
            {
                "restore_id": restore_id,
                "dataset_id": dataset_id,
                "membership": {key: value for key, value in item.items() if key != "_id"},
                "created_at": now(),
                "expires_at": expires_at,
            }
            for item in members
        ])


async def _restore_memberships_from_backup(dataset_id: str, restore_id: str) -> None:
    await db.dataset_memberships.delete_many({"dataset_id": dataset_id})
    cursor = db.dataset_restore_backups.find({"restore_id": restore_id}).sort(
        "created_at", ASCENDING
    )
    async for rows in cursor_batches(cursor):
        await db.dataset_memberships.insert_many([row["membership"] for row in rows])


async def _resume_pending_restore(dataset_id: str) -> None:
    dataset = await db.datasets.find_one(
        {"id": dataset_id},
        {"restore_target_version_id": 1, "restore_actor_id": 1, "restore_backup_id": 1},
    )
    if not dataset or not dataset.get("restore_target_version_id"):
        return
    version_id = dataset["restore_target_version_id"]
    version = await db.dataset_versions.find_one({"id": version_id, "dataset_id": dataset_id})
    if version is None:
        raise AppError(409, "DATASET_RESTORE_INVALID", "未完成的版本恢复指向无效版本")
    await _restore_memberships_from_version(dataset_id, version_id, dataset.get("restore_actor_id") or "system")
    await db.datasets.update_one({"id": dataset_id}, {"$set": {"current_version_id": version_id, "current_version": version["version"]}})
    if dataset.get("restore_backup_id"):
        with suppress(Exception):
            await db.dataset_restore_backups.delete_many({"restore_id": dataset["restore_backup_id"]})
    await db.datasets.update_one(
        {"id": dataset_id},
        {"$unset": {
            "restore_target_version_id": "", "restore_actor_id": "", "restore_backup_id": "",
        }},
    )


async def _validate_status(value: str) -> None:
    definition = await db.tag_definitions.find_one({"key": "status"})
    values = (definition or {}).get("values", [])
    if values and value not in values:
        raise AppError(400, "DATASET_STATUS_INVALID", "状态不在标签管理的可选值中")


async def _validate_projects(values: list[str]) -> None:
    definition = await db.tag_definitions.find_one({"key": "project"})
    options = (definition or {}).get("values", [])
    if not options:
        raise AppError(400, "DATASET_PROJECT_UNAVAILABLE", "请先在标签管理中添加项目")
    if any(value not in options for value in values):
        raise AppError(400, "DATASET_PROJECT_INVALID", "所属项目不在标签管理的可选值中")


async def _get_dataset(dataset_id: str) -> dict[str, Any]:
    dataset = await db.datasets.find_one({"id": dataset_id, "deleted_at": None})
    if dataset is None:
        raise AppError(404, "DATASET_NOT_FOUND", "数据集不存在")
    return dataset


def _classification(dataset: dict[str, Any]) -> tuple[str, dict[str, str]]:
    rule = dataset.get("classification_rule", "standard")
    labels = (dict(SPLIT_LABELS) if rule == "standard" else
              {**dataset.get("custom_categories", {}), "unassigned": "未划分"} if rule == "custom" else {})
    return rule, labels


def _validate_category_name(name: str, labels: dict[str, str], exclude: str = "") -> str:
    name = name.strip()
    if not name or len(name) > 40 or name == "未划分":
        raise AppError(400, "DATASET_CATEGORY_NAME_INVALID", "分类名称须为 1 至 40 字，且不能为未划分")
    if any(value.casefold() == name.casefold() for key, value in labels.items() if key != exclude):
        raise AppError(409, "DATASET_CATEGORY_NAME_EXISTS", "分类名称已存在")
    return name


def _export_category_folders(labels: dict[str, str], selected: set[str]) -> dict[str, str]:
    folders: dict[str, str] = {}
    used: set[str] = set()
    for category_id in sorted(selected):
        label = labels[category_id]
        folder = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", label).strip(" .") or "分类"
        if folder.casefold() in used:
            suffix = 2
            while f"{folder} ({suffix})".casefold() in used:
                suffix += 1
            folder = f"{folder} ({suffix})"
        used.add(folder.casefold())
        folders[category_id] = folder
    return folders


def _asset_snapshot(asset: dict[str, Any]) -> dict[str, Any]:
    snapshot = {
        "name": asset.get("name", ""),
        "type": asset.get("type", "other"),
        "size": int(asset.get("size") or 0),
        "sha256": asset.get("sha256"),
        "tags": asset.get("tags") or {},
        "remark": asset.get("remark") or "",
        "updated_at": asset.get("updated_at"),
    }
    if asset.get("type") == "image":
        snapshot["split"] = asset.get("_dataset_split", "unassigned")
        if asset.get("_dataset_split_label"):
            snapshot["split_label"] = asset["_dataset_split_label"]
    return snapshot


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
    for offset in range(0, len(changes["added"]), 1000):
        operations = [
            UpdateOne(
                {"dataset_id": dataset_id, "asset_id": annotation_id},
                {"$setOnInsert": {"id": new_id(), "dataset_id": dataset_id,
                                  "asset_id": annotation_id, "created_by": actor_id,
                                  "created_at": now()}},
                upsert=True,
            )
            for annotation_id in changes["added"][offset:offset + 1000]
        ]
        await db.dataset_memberships.bulk_write(operations, ordered=False)
    if changes["removed"]:
        await db.dataset_memberships.delete_many({"dataset_id": dataset_id, "asset_id": {"$in": changes["removed"]}})
    if changes["added"] or changes["removed"]:
        await db.datasets.update_one({"id": dataset_id}, {"$set": {"updated_at": now()}})
    return changes


async def _publication_quality(dataset_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rule, labels = _classification(await _get_dataset(dataset_id))
    member_ids = await db.dataset_memberships.distinct("asset_id", {"dataset_id": dataset_id})
    assets = await db.assets.find({"id": {"$in": member_ids}, "archived_at": None, "type": {"$ne": "model"}}).sort("id", ASCENDING).to_list(length=len(member_ids)) if member_ids else []
    image_ids_for_splits = [item["id"] for item in assets if item.get("type") == "image"]
    split_rows = await db.dataset_memberships.find({"dataset_id": dataset_id, "asset_id": {"$in": image_ids_for_splits}}, {"asset_id": 1, "split": 1}).to_list(length=None) if image_ids_for_splits else []
    splits = {item["asset_id"]: split_of(item) for item in split_rows}
    for asset in assets:
        if asset.get("type") == "image":
            asset["_dataset_split"] = splits.get(asset["id"], "unassigned")
            asset["_dataset_split_label"] = labels.get(asset["_dataset_split"], "未划分")
    valid_ids = {item["id"] for item in assets}
    invalid_ids = sorted(set(member_ids) - valid_ids)
    images = [item for item in assets if item.get("type") == "image"]
    image_ids = [item["id"] for item in images]
    relations = await db.relations.find({"relation_type": "annotates", "status": "active", "target_id": {"$in": image_ids}}, {"source_id": 1, "target_id": 1}).to_list(length=None) if image_ids else []
    annotation_ids = list({item["source_id"] for item in relations})
    valid_annotations = {item["id"] for item in await db.assets.find({"id": {"$in": annotation_ids}, "type": "annotation", "archived_at": None}, {"id": 1}).to_list(length=None)} if annotation_ids else set()
    labeled_images = {item["target_id"] for item in relations if item["source_id"] in valid_annotations}
    unlabeled = [item for item in images if item["id"] not in labeled_images]
    hashes: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for asset in assets:
        if asset.get("sha256"):
            hashes.setdefault((asset["sha256"].lower(), int(asset.get("size") or 0)), []).append(asset)
    duplicates = [item for group in hashes.values() for item in group[1:]]
    cross_split = [item for group in hashes.values() if len({item.get("_dataset_split") for item in group if item.get("type") == "image" and item.get("_dataset_split") in labels and item.get("_dataset_split") != "unassigned"}) > 1 for item in group if item.get("type") == "image"]
    unassigned = [item for item in images if item["_dataset_split"] == "unassigned"] if rule != "none" else []
    annotation_targets: dict[str, set[str]] = {}
    for relation in relations:
        if relation["source_id"] in valid_annotations:
            annotation_targets.setdefault(relation["source_id"], set()).add(relation["target_id"])
    shared_annotations = [{"id": annotation_id, "image_ids": sorted(targets), "cross_split": len({splits.get(image_id, "unassigned") for image_id in targets}) > 1} for annotation_id, targets in annotation_targets.items() if len(targets) > 1]
    counts: dict[str, int] = {}
    for asset in assets:
        kind = asset.get("type", "other")
        counts[kind] = counts.get(kind, 0) + 1
    issues = {
        "invalid_assets": [{"id": item} for item in invalid_ids],
        "unlabeled_images": [{"id": item["id"], "name": item.get("name", "")} for item in unlabeled],
        "duplicate_assets": [{"id": item["id"], "name": item.get("name", "")} for item in duplicates],
        "unassigned_images": [{"id": item["id"], "name": item.get("name", "")} for item in unassigned],
        "cross_split_duplicates": [{"id": item["id"], "name": item.get("name", "")} for item in cross_split],
        "shared_annotations": shared_annotations,
    }
    blockers = (["empty_dataset"] if not assets else []) + (["invalid_assets"] if invalid_ids else [])
    warnings = [key for key in ("unlabeled_images", "duplicate_assets", "unassigned_images", "cross_split_duplicates", "shared_annotations") if issues[key] and (rule != "none" or key not in {"unassigned_images", "cross_split_duplicates"})]
    evidence = {"members": sorted(member_ids), "assets": [{"id": item["id"], "snapshot": _asset_snapshot(item)} for item in assets], "relations": sorted((item["source_id"], item["target_id"]) for item in relations if item["source_id"] in valid_annotations)}
    token = hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()
    return {"token": token, "member_count": len(assets), "counts": counts, "blockers": blockers, "warnings": warnings, "issues": issues, "missing_hash_count": sum(not item.get("sha256") for item in assets)}, assets


@router.get("/{dataset_id}/publication-quality")
async def publication_quality(dataset_id: str, user: DatasetVersionPublishUser) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    report, _ = await _publication_quality(dataset_id)
    return report


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
    result.pop("algorithms", None)
    result.setdefault("projects", [])
    result.update({"member_count": sum(counts.values()), "counts": counts, "total_size": total_size})
    return result


async def _dataset_summaries(datasets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not datasets:
        return []
    counts: dict[str, dict[str, int]] = {item["id"]: {} for item in datasets}
    sizes: dict[str, int] = {item["id"]: 0 for item in datasets}
    pipeline = [
        {"$match": {"dataset_id": {"$in": list(counts)}}},
        {"$lookup": {"from": "assets", "localField": "asset_id", "foreignField": "id", "as": "asset"}},
        {"$unwind": "$asset"},
        {"$match": {"asset.archived_at": None}},
        {"$group": {"_id": {"dataset_id": "$dataset_id", "type": "$asset.type"},
                     "count": {"$sum": 1}, "size": {"$sum": {"$ifNull": ["$asset.size", 0]}}}},
    ]
    async for row in await db.dataset_memberships.aggregate(pipeline):
        dataset_id = row["_id"]["dataset_id"]
        counts[dataset_id][row["_id"]["type"]] = row["count"]
        sizes[dataset_id] += row["size"]
    result = []
    for item in datasets:
        summary = public_document(item) or {}
        summary.pop("algorithms", None)
        summary.setdefault("projects", [])
        summary.update({"member_count": sum(counts[item["id"]].values()),
                        "counts": counts[item["id"]], "total_size": sizes[item["id"]]})
        result.append(summary)
    return result


@router.post("", status_code=201)
async def create_dataset(body: DatasetCreate, request: Request, user: DatasetCreateEditUser) -> dict[str, Any]:
    await _validate_status(body.status)
    await _validate_projects(body.projects)
    timestamp = now()
    dataset = {
        "id": new_id(), "name": body.name.strip(), "remark": body.remark,
        "status": body.status, "projects": body.projects,
        "classification_rule": body.classification_rule, "custom_categories": {},
        "current_version_id": None, "current_version": None,
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
    user: DatasetReadUser, q: str | None = None, status: str | None = None,
    creator: str | None = None, updated_from: str | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = [{"deleted_at": None}]
    if q:
        keyword = re.escape(q.strip())
        clauses.append({"$or": [{"name": {"$regex": keyword, "$options": "i"}}, {"remark": {"$regex": keyword, "$options": "i"}}]})
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
    cursor = db.datasets.find(query).sort([("updated_at", DESCENDING), ("id", ASCENDING)]).skip((page - 1) * page_size).limit(page_size)
    return {"items": await _dataset_summaries(await cursor.to_list(length=None)),
            "page": page, "page_size": page_size, "total": total}


@router.get("/options")
async def dataset_options(
    user: DatasetReadUser,
    q: str = Query("", max_length=120),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
) -> dict[str, Any]:
    query: dict[str, Any] = {"deleted_at": None, "current_version_id": {"$ne": None}}
    if q.strip():
        query["name"] = {"$regex": re.escape(q.strip()), "$options": "i"}
    total = await db.datasets.count_documents(query)
    cursor = (
        db.datasets.find(
            query,
            {"_id": 0, "id": 1, "name": 1, "current_version": 1, "current_version_id": 1},
        )
        .sort([("name", ASCENDING), ("id", ASCENDING)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    return {"items": [item async for item in cursor], "page": page, "page_size": page_size, "total": total}


@router.get("/creators")
async def dataset_creators(user: DatasetReadUser) -> dict[str, Any]:
    names = await db.datasets.distinct("created_by_name", {"deleted_at": None})
    return {"items": sorted(name for name in names if name)}


class DatasetCopyRequest(BaseModel):
    include_assets: bool = False
    name: str = Field(min_length=1, max_length=100)


@router.post("/{dataset_id}/copy", status_code=201)
@serialize_dataset_write
async def copy_dataset(dataset_id: str, body: DatasetCopyRequest, request: Request, user: DatasetCreateEditUser) -> dict[str, Any]:
    original = await _get_dataset(dataset_id)
    name = body.name.strip()
    if not name:
        raise AppError(400, "DATASET_NAME_EMPTY", "请输入数据集名称")
    if not original.get("projects"):
        raise AppError(400, "DATASET_PROJECT_REQUIRED", "请先编辑原数据集并补全所属项目")
    copied = await create_dataset(DatasetCreate(
        name=name, remark=original.get("remark", ""), status=original["status"],
        projects=original["projects"], classification_rule=original.get("classification_rule", "standard"),
    ), request, user)
    if original.get("classification_rule") == "custom":
        await db.datasets.update_one({"id": copied["id"]}, {"$set": {"custom_categories": original.get("custom_categories", {})}})
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
                batch.append({"id": new_id(), "dataset_id": copied["id"], "asset_id": item["asset_id"], "split": split_of(item) if item["asset"]["type"] == "image" else None, "created_by": user["id"], "created_at": now()})
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
async def dataset_tag_distribution(dataset_id: str, user: DatasetReadUser) -> dict[str, Any]:
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
async def get_dataset(dataset_id: str, user: DatasetReadUser) -> dict[str, Any]:
    return await _dataset_summary(await _get_dataset(dataset_id))


@router.patch("/{dataset_id}")
@serialize_dataset_write
async def update_dataset(dataset_id: str, body: DatasetUpdate, request: Request, user: DatasetCreateEditUser) -> dict[str, Any]:
    dataset = await _get_dataset(dataset_id)
    await _validate_status(body.status)
    await _validate_projects(body.projects)
    next_rule = body.classification_rule or dataset.get("classification_rule", "standard")
    changed_rule = next_rule != dataset.get("classification_rule", "standard")
    if changed_rule:
        await db.dataset_memberships.update_many({"dataset_id": dataset_id, "split": {"$ne": None}}, {"$set": {"split": "unassigned", "split_updated_at": now()}})
    await db.datasets.update_one({"id": dataset_id}, {"$set": {"name": body.name.strip(), "remark": body.remark, "status": body.status, "projects": body.projects, "classification_rule": next_rule, "custom_categories": {} if changed_rule else dataset.get("custom_categories", {}), "updated_at": now()}})
    await record_audit(actor=user, action="dataset.updated", object_type="dataset", object_id=dataset_id, request_id=request.state.request_id)
    return await _dataset_summary(await _get_dataset(dataset_id))


class DatasetCategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)


@router.post("/{dataset_id}/categories", status_code=201)
@serialize_dataset_write
async def create_category(dataset_id: str, body: DatasetCategoryRequest, request: Request, user: DatasetMembersUser) -> dict[str, Any]:
    dataset = await _get_dataset(dataset_id)
    if dataset.get("classification_rule") != "custom":
        raise AppError(400, "DATASET_CATEGORY_RULE_INVALID", "仅自定义规则可管理分类")
    categories = dict(dataset.get("custom_categories") or {})
    if len(categories) >= 30:
        raise AppError(400, "DATASET_CATEGORY_LIMIT", "最多添加 30 个分类")
    name = _validate_category_name(body.name, categories)
    key = "custom_" + new_id().replace("-", "")
    categories[key] = name
    await db.datasets.update_one({"id": dataset_id}, {"$set": {"custom_categories": categories, "updated_at": now()}})
    await record_audit(actor=user, action="dataset.category_created", object_type="dataset", object_id=dataset_id, request_id=request.state.request_id, changes={"category": key, "name": name})
    return {"key": key, "name": name, "categories": categories}


@router.patch("/{dataset_id}/categories/{category_id}")
@serialize_dataset_write
async def rename_category(dataset_id: str, category_id: str, body: DatasetCategoryRequest, request: Request, user: DatasetMembersUser) -> dict[str, Any]:
    dataset = await _get_dataset(dataset_id)
    categories = dict(dataset.get("custom_categories") or {})
    if dataset.get("classification_rule") != "custom" or category_id not in categories:
        raise AppError(404, "DATASET_CATEGORY_NOT_FOUND", "分类不存在")
    name = _validate_category_name(body.name, categories, category_id)
    categories[category_id] = name
    await db.datasets.update_one({"id": dataset_id}, {"$set": {"custom_categories": categories, "updated_at": now()}})
    await record_audit(actor=user, action="dataset.category_renamed", object_type="dataset", object_id=dataset_id, request_id=request.state.request_id, changes={"category": category_id, "name": name})
    return {"key": category_id, "name": name, "categories": categories}


@router.delete("/{dataset_id}/categories/{category_id}")
@serialize_dataset_write
async def delete_category(dataset_id: str, category_id: str, request: Request, user: DatasetMembersUser) -> dict[str, Any]:
    dataset = await _get_dataset(dataset_id)
    categories = dict(dataset.get("custom_categories") or {})
    if dataset.get("classification_rule") != "custom" or category_id not in categories:
        raise AppError(404, "DATASET_CATEGORY_NOT_FOUND", "分类不存在")
    del categories[category_id]
    result = await db.dataset_memberships.update_many({"dataset_id": dataset_id, "split": category_id}, {"$set": {"split": "unassigned", "split_updated_at": now()}})
    await db.datasets.update_one({"id": dataset_id}, {"$set": {"custom_categories": categories, "updated_at": now()}})
    await record_audit(actor=user, action="dataset.category_deleted", object_type="dataset", object_id=dataset_id, request_id=request.state.request_id, changes={"category": category_id, "reset_count": result.modified_count})
    return {"reset_count": result.modified_count, "categories": categories}


@router.delete("/{dataset_id}", status_code=204)
@serialize_dataset_write
async def delete_dataset(dataset_id: str, request: Request, user: DatasetDeleteUser) -> None:
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
async def list_members(dataset_id: str, user: DatasetReadUser, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), q: str = "", asset_type: list[str] = Query(default=[]), tag: list[str] = Query(default=[]), match: str = Query("all", pattern="^(all|any)$"), no_tags: bool = False, ids_only: bool = False, split: list[str] = Query(default=[])) -> dict[str, Any]:
    _, labels = _classification(await _get_dataset(dataset_id))
    if any(value not in {"all", *labels} for value in split):
        raise AppError(400, "INVALID_SPLIT_FILTER", "图片用途筛选条件不正确")
    selected_splits = set(split) - {"all"} if "all" not in split else set()
    clauses = [{"archived_at": None}, {"type": {"$ne": "annotation"}}]
    if q:
        import re
        clauses.append({"$or": [{"name": {"$regex": re.escape(q), "$options": "i"}}, {"remark": {"$regex": re.escape(q), "$options": "i"}}]})
    if asset_type:
        clauses.append({"type": {"$in": asset_type}})
    if selected_splits:
        clauses.append({"type": "image", "dataset_split": {"$in": sorted(selected_splits)}})
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
        {"$addFields": {"asset.dataset_split": {"$cond": [{"$eq": ["$asset.type", "image"]}, {"$ifNull": ["$split", "unassigned"]}, None]}}},
        {"$replaceRoot": {"newRoot": "$asset"}},
        {"$match": {"$and": clauses}},
        {"$sort": {"created_at": -1, "id": 1}},

    ]
    if selected_splits:
        membership_splits = sorted(selected_splits | ({None} if "unassigned" in selected_splits else set()), key=lambda value: value or "")
        pipeline.insert(1, {"$match": {"split": {"$in": membership_splits}}})
    count_cursor = await db.dataset_memberships.aggregate([*pipeline, {"$count": "count"}])
    counts = await count_cursor.to_list(length=1)
    total = counts[0]["count"] if counts else 0
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
async def member_status(dataset_id: str, body: DatasetMembersRequest, user: DatasetReadUser) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    ids = list(dict.fromkeys(body.asset_ids))
    existing = await db.dataset_memberships.distinct("asset_id", {
        "dataset_id": dataset_id, "asset_id": {"$in": ids},
    }) if ids else []
    return {"existing_ids": existing}


async def _split_images(dataset_id: str) -> list[dict[str, Any]]:
    rows = await db.dataset_memberships.find({"dataset_id": dataset_id}, {"asset_id": 1, "split": 1}).to_list(length=None)
    if not rows:
        return []
    assets = await db.assets.find({"id": {"$in": [row["asset_id"] for row in rows]}, "type": "image", "archived_at": None}, {"id": 1, "name": 1, "sha256": 1, "size": 1}).to_list(length=None)
    members = {row["asset_id"]: row for row in rows}
    return [{**asset, "split": split_of(members[asset["id"]])} for asset in assets]


@router.get("/{dataset_id}/split-stats")
async def split_stats(dataset_id: str, user: DatasetReadUser) -> dict[str, Any]:
    dataset = await _get_dataset(dataset_id)
    images = await _split_images(dataset_id)
    _, labels = _classification(dataset)
    counts = {split: sum(split_of(item) == split for item in images) for split in labels}
    return {"image_count": len(images), "counts": counts, "labels": labels}


@router.patch("/{dataset_id}/members/split")
@serialize_dataset_write
async def update_member_split(dataset_id: str, body: DatasetSplitUpdate, request: Request, user: DatasetMembersUser) -> dict[str, Any]:
    dataset = await _get_dataset(dataset_id)
    if body.split not in _classification(dataset)[1]:
        raise AppError(400, "DATASET_SPLIT_INVALID", "分类不属于当前数据集")
    ids = list(dict.fromkeys(body.asset_ids))
    images = await _split_images(dataset_id)
    valid = {item["id"] for item in images}
    if len(ids) != len(body.asset_ids) or not set(ids) <= valid:
        raise AppError(400, "DATASET_SPLIT_ASSETS_INVALID", "只能为当前数据集的图片设置用途")
    result = await db.dataset_memberships.update_many(
        {"dataset_id": dataset_id, "asset_id": {"$in": ids}},
        {"$set": {"split": body.split, "split_updated_at": now()}},
    )
    await db.datasets.update_one({"id": dataset_id}, {"$set": {"updated_at": now()}})
    await record_audit(actor=user, action="dataset.split_updated", object_type="dataset", object_id=dataset_id, request_id=request.state.request_id, changes={"split": body.split, "count": result.matched_count})
    return {"updated": result.matched_count, "split": body.split}


async def _auto_split_report(dataset_id: str, body: DatasetAutoSplitRequest) -> dict[str, Any]:
    dataset = await _get_dataset(dataset_id)
    rule, labels = _classification(dataset)
    if rule == "none" or (rule == "custom" and not dataset.get("custom_categories")):
        raise AppError(400, "DATASET_SPLIT_UNAVAILABLE", "当前没有可分配的分类")
    images = await _split_images(dataset_id)
    ratios = (body.ratios if rule == "custom" else {"train": body.train, "val": body.val, "test": body.test})
    if not ratios or set(ratios) != set(labels) - {"unassigned"} or any(not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 10000 for value in ratios.values()) or not any(ratios.values()):
        raise AppError(400, "DATASET_SPLIT_RATIOS_INVALID", "分配比例与当前分类不一致")
    preview = allocation_preview(dataset_id, images, ratios)
    evidence = {"dataset_id": dataset_id, "ratios": ratios, "labels": labels, "images": sorted((item["id"], item.get("sha256"), item.get("size"), item["split"]) for item in images)}
    preview["token"] = hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()
    return preview


@router.post("/{dataset_id}/auto-split/preview")
async def preview_auto_split(dataset_id: str, body: DatasetAutoSplitRequest, user: DatasetMembersUser) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    preview = await _auto_split_report(dataset_id, body)
    return {key: value for key, value in preview.items() if key != "assignments"}


@router.post("/{dataset_id}/auto-split")
@serialize_dataset_write
async def apply_auto_split(dataset_id: str, body: DatasetAutoSplitRequest, request: Request, user: DatasetMembersUser) -> dict[str, Any]:
    dataset = await _get_dataset(dataset_id)
    preview = await _auto_split_report(dataset_id, body)
    if body.preview_token != preview["token"]:
        raise AppError(409, "DATASET_SPLIT_CHANGED", "图片或用途已变化，请重新预览")
    for split in _classification(dataset)[1]:
        if split == "unassigned":
            continue
        ids = [asset_id for asset_id, value in preview["assignments"].items() if value == split]
        if ids:
            await db.dataset_memberships.update_many({"dataset_id": dataset_id, "asset_id": {"$in": ids}, "split": {"$in": [None, "unassigned"]}}, {"$set": {"split": split, "split_updated_at": now()}})
    if preview["allocated_count"]:
        await db.datasets.update_one({"id": dataset_id}, {"$set": {"updated_at": now()}})
    await record_audit(actor=user, action="dataset.auto_split", object_type="dataset", object_id=dataset_id, request_id=request.state.request_id, changes={"counts": preview["counts"], "skipped_count": len(preview["skipped"])})
    return {key: value for key, value in preview.items() if key != "assignments"}


@router.post("/{dataset_id}/members")
@serialize_dataset_write
async def add_members(dataset_id: str, body: DatasetMembersRequest, request: Request, user: DatasetMembersUser) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    ids = await resolve_selection_ids(user, body.asset_ids, body.selection_id, body.excluded_ids)
    assets = await db.assets.find({"id": {"$in": ids}, "archived_at": None}).to_list(length=len(ids))
    valid = [item for item in assets if item.get("type") not in {"model", "annotation"}]
    invalid_ids = sorted(set(ids) - {item["id"] for item in valid})
    timestamp = now()
    added = 0
    added_ids: list[str] = []
    for asset in valid:
        result = await db.dataset_memberships.update_one(
            {"dataset_id": dataset_id, "asset_id": asset["id"]},
            {"$setOnInsert": {"id": new_id(), "dataset_id": dataset_id, "asset_id": asset["id"], "split": "unassigned" if asset["type"] == "image" else None, "created_by": user["id"], "created_at": timestamp}},
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
async def preview_members(dataset_id: str, body: DatasetMembersRequest, user: DatasetReadUser, action: str = Query("add", pattern="^(add|remove)$")) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    requested = set(await resolve_selection_ids(user, body.asset_ids, body.selection_id, body.excluded_ids))
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
async def remove_members(dataset_id: str, body: DatasetMembersRequest, request: Request, user: DatasetMembersUser) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    ids = await resolve_selection_ids(user, body.asset_ids, body.selection_id, body.excluded_ids)
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
async def publish_version(dataset_id: str, body: DatasetPublishRequest, request: Request, user: DatasetVersionPublishUser) -> dict[str, Any]:
    dataset = await _get_dataset(dataset_id)
    report, assets = await _publication_quality(dataset_id)
    if body.quality_token != report["token"]:
        raise AppError(409, "DATASET_QUALITY_CHANGED", "数据集质量检查结果已变化，请刷新后重试")
    member_ids = await db.dataset_memberships.distinct("asset_id", {"dataset_id": dataset_id})
    invalid_ids = sorted(set(member_ids) - {item["id"] for item in assets})
    if invalid_ids:
        raise AppError(409, "DATASET_HAS_INVALID_ASSETS", "数据集中包含已删除或失效素材", {"asset_ids": invalid_ids})
    if not assets:
        raise AppError(400, "DATASET_EMPTY", "数据集中没有可发布的素材")
    if report["warnings"] and not body.acknowledge_warnings:
        raise AppError(409, "DATASET_QUALITY_ACK_REQUIRED", "请先确认数据集质量风险")
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
    version = {"id": new_id(), "dataset_id": dataset_id, "name": f"{dataset['name']} {version_name}", "kind": "dataset_version", "version": version_name, "version_number": number, "release_note": body.release_note, "member_count": len(members), "total_size": sum(m["snapshot"]["size"] for m in members), "content_digest": digest, "quality_summary": {"warnings": {key: len(report["issues"][key]) for key in report["warnings"]}, "missing_hash_count": report["missing_hash_count"], "acknowledged": body.acknowledge_warnings}, "created_by": user["id"], "created_by_name": user.get("username", user["id"]), "created_at": timestamp}
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
    await record_audit(actor=user, action="dataset.version_published", object_type="dataset_version", object_id=version["id"], request_id=request.state.request_id, changes={"quality_summary": version["quality_summary"]})
    return public_document(version) or {}


@router.get("/{dataset_id}/versions")
async def list_versions(dataset_id: str, user: DatasetReadUser) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    return {"items": [public_document(item) async for item in db.dataset_versions.find({"dataset_id": dataset_id}).sort("version_number", DESCENDING)]}


@router.get("/{dataset_id}/models")
async def list_dataset_models(dataset_id: str, user: DatasetReadUser) -> dict[str, Any]:
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
    configured_metric_ids = {
        metric_id
        for model in models.values()
        for metric_id, value in (model.get("metric_values") or {}).items()
        if value is not None and str(value).strip()
    }
    metric_definitions = {
        item["id"]: item
        for item in (
            await db.metric_definitions.find(
                {"id": {"$in": list(configured_metric_ids)}}
            ).to_list(length=len(configured_metric_ids))
            if configured_metric_ids
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
                "configured_parameters": sorted(
                    [
                        {
                            "id": metric_id,
                            "name": metric_definitions[metric_id]["name"],
                            "category": metric_definitions[metric_id]["category"],
                            "value": str(value),
                        }
                        for metric_id, value in (models[relation["source_id"]].get("metric_values") or {}).items()
                        if metric_id in metric_definitions and value is not None and str(value).strip()
                    ],
                    key=lambda item: (item["category"], item["name"]),
                ),
            }
            for relation in relations
            if relation["source_id"] in models
        ]
    }


@router.post("/{dataset_id}/models")
@serialize_dataset_write
async def add_dataset_model(
    dataset_id: str, body: DatasetModelLinkRequest, request: Request, user: DatasetModelUser
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


@router.patch("/{dataset_id}/models/{relation_id}")
@serialize_dataset_write
async def update_dataset_model_remark(
    dataset_id: str, relation_id: str, body: DatasetModelRemarkUpdate,
    request: Request, user: DatasetModelUser,
) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    relation = await db.relations.find_one(
        {"id": relation_id, "relation_type": "trained_on", "status": "active"}
    )
    if relation is None:
        raise AppError(404, "RELATION_NOT_FOUND", "模型关联关系不存在")
    version = await db.dataset_versions.find_one(
        {"id": relation["target_id"], "dataset_id": dataset_id}
    )
    if version is None:
        raise AppError(400, "DATASET_MODEL_LINK_INVALID", "该关系不属于当前数据集")
    previous_remark = (relation.get("provenance") or {}).get("remark", "")
    remark = body.remark.strip()
    result = await db.relations.update_one(
        {"id": relation_id, "relation_type": "trained_on", "status": "active"},
        {"$set": {"provenance.remark": remark}},
    )
    if not result.matched_count:
        raise AppError(404, "RELATION_NOT_FOUND", "模型关联关系不存在")
    await record_audit(
        actor=user, action="dataset.model_link_remark_updated",
        object_type="relation", object_id=relation_id,
        request_id=request.state.request_id,
        changes={"dataset_id": dataset_id, "version_id": relation["target_id"],
                 "previous_remark": previous_remark, "remark": remark},
    )
    relation.setdefault("provenance", {})["remark"] = remark
    return {"relation": public_document(relation)}


@router.delete("/{dataset_id}/models/{relation_id}")
@serialize_dataset_write
async def remove_dataset_model(
    dataset_id: str, relation_id: str, request: Request, user: DatasetModelUser
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
async def get_version(
    dataset_id: str,
    version_id: str,
    user: DatasetReadUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    version = await db.dataset_versions.find_one({"id": version_id, "dataset_id": dataset_id})
    if version is None:
        raise AppError(404, "DATASET_VERSION_NOT_FOUND", "数据集版本不存在")
    total = await db.dataset_version_memberships.count_documents({"version_id": version_id})
    cursor = db.dataset_version_memberships.find({"version_id": version_id}).sort(
        "asset_id", ASCENDING
    ).skip((page - 1) * page_size).limit(page_size)
    items = [public_document(item) async for item in cursor]
    return {
        **(public_document(version) or {}),
        "members": items,
        "member_total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{dataset_id}/compare")
async def compare_versions(dataset_id: str, from_version_id: str, to_version_id: str, user: DatasetReadUser) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    versions = await db.dataset_versions.find({"dataset_id": dataset_id, "id": {"$in": [from_version_id, to_version_id]}}).to_list(length=2)
    if len(versions) != 2 or from_version_id == to_version_id:
        raise AppError(400, "DATASET_VERSION_COMPARE_INVALID", "请选择两个不同的数据集版本")
    return await compare_version_memberships(
        db, from_version_id, to_version_id, DATASET_COMPARE_DETAIL_LIMIT
    )


@router.post("/{dataset_id}/restore")
@serialize_dataset_write
async def restore_version(dataset_id: str, body: DatasetRestoreRequest, request: Request, user: DatasetVersionRestoreUser) -> dict[str, Any]:
    await _get_dataset(dataset_id)
    version = await db.dataset_versions.find_one({"id": body.version_id, "dataset_id": dataset_id})
    if version is None:
        raise AppError(404, "DATASET_VERSION_NOT_FOUND", "数据集版本不存在")
    invalid = []
    member_count = 0
    member_cursor = db.dataset_version_memberships.find({"version_id": body.version_id}).sort(
        "asset_id", ASCENDING
    )
    async for members in cursor_batches(member_cursor):
        member_ids = [item["asset_id"] for item in members]
        valid_ids = set(await db.assets.distinct(
            "id", {"id": {"$in": member_ids}, "archived_at": None, "type": {"$ne": "model"}}
        ))
        invalid.extend(asset_id for asset_id in member_ids if asset_id not in valid_ids)
        member_count += len(members)
    if invalid:
        raise AppError(409, "DATASET_HAS_INVALID_ASSETS", "版本中包含已删除或失效素材", {"asset_ids": sorted(invalid)})
    restore_id = new_id()
    await _backup_dataset_memberships(dataset_id, restore_id)
    await db.datasets.update_one(
        {"id": dataset_id},
        {"$set": {
            "restore_target_version_id": body.version_id,
            "restore_actor_id": user["id"],
            "restore_backup_id": restore_id,
        }},
    )
    try:
        await _restore_memberships_from_version(dataset_id, body.version_id, user["id"])
        await db.datasets.update_one({"id": dataset_id}, {"$set": {"current_version_id": body.version_id, "current_version": version["version"]}})
    except Exception:
        await _restore_memberships_from_backup(dataset_id, restore_id)
        with suppress(Exception):
            await db.dataset_restore_backups.delete_many({"restore_id": restore_id})
        await db.datasets.update_one(
            {"id": dataset_id},
            {"$unset": {
                "restore_target_version_id": "", "restore_actor_id": "", "restore_backup_id": "",
            }},
        )
        raise
    await record_audit(actor=user, action="dataset.version_restored", object_type="dataset", object_id=dataset_id, request_id=request.state.request_id, changes={"version_id": body.version_id})
    await db.datasets.update_one(
        {"id": dataset_id},
        {"$unset": {
            "restore_target_version_id": "", "restore_actor_id": "", "restore_backup_id": "",
        }},
    )
    with suppress(Exception):
        await db.dataset_restore_backups.delete_many({"restore_id": restore_id})
    return {"restored": member_count}


@router.post("/{dataset_id}/export", status_code=202)
@serialize_dataset_write
async def export_dataset(dataset_id: str, body: DatasetExportRequest, request: Request, user: DatasetExportUser) -> dict[str, Any]:
    dataset = await _get_dataset(dataset_id)
    rule, labels = _classification(dataset)
    if body.export_type == "categories" and any(split not in labels for split in body.splits):
        raise AppError(400, "DATASET_EXPORT_CATEGORY_INVALID", "导出分类不属于当前数据集")
    if body.export_type in {*SPLITS, "unassigned"} and body.export_type not in labels:
        raise AppError(400, "DATASET_EXPORT_CATEGORY_INVALID", "导出分类不属于当前数据集")
    memberships = await db.dataset_memberships.find({"dataset_id": dataset_id}, {"asset_id": 1, "split": 1}).to_list(length=None)
    asset_ids = [item["asset_id"] for item in memberships]
    assets = {item["id"]: item for item in await db.assets.find({"id": {"$in": asset_ids}, "archived_at": None}, {"id": 1, "name": 1, "type": 1}).to_list(length=None)}
    image_splits = {item["asset_id"]: split_of(item) for item in memberships if assets.get(item["asset_id"], {}).get("type") == "image"}
    if body.export_type == "current":
        invalid = sorted(set(body.asset_ids) - {item for item in asset_ids if assets.get(item, {}).get("type") != "annotation"})
        if invalid:
            raise AppError(400, "DATASET_EXPORT_SELECTION_INVALID", "所选成员已不在当前数据集中，请重新选择", {"asset_ids": invalid})
    selected_splits = set(body.splits if body.export_type == "categories" else [body.export_type] if body.export_type in {*SPLITS, "unassigned"} else [])
    category_folders = _export_category_folders(labels, selected_splits)
    selected_images = ({item for item in body.asset_ids if item in image_splits} if body.export_type == "current" else {item for item, split in image_splits.items() if split in selected_splits} if selected_splits else set(image_splits))
    relations = await db.relations.find({"relation_type": "annotates", "status": "active", "source_id": {"$in": [item for item in asset_ids if assets.get(item, {}).get("type") == "annotation"]}}, {"source_id": 1, "target_id": 1}).to_list(length=None)
    annotation_splits: dict[str, set[str]] = {}
    annotation_targets: dict[str, set[str]] = {}
    for relation in relations:
        annotation_targets.setdefault(relation["source_id"], set()).add(relation["target_id"])
        annotation_splits.setdefault(relation["source_id"], set()).add(image_splits.get(relation["target_id"], "external"))
    if body.include_annotations and body.export_type != "all":
        conflicts = sorted(annotation_id for annotation_id, targets in annotation_targets.items() if targets & selected_images and (
            not targets <= selected_images
            or (bool(selected_splits) and len({image_splits[target] for target in targets & selected_images}) > 1)
        ))
        if conflicts:
            raise AppError(409, "DATASET_EXPORT_SHARED_ANNOTATION", "标注关联了导出范围外或不同分类的图片，请先修正关系", {"asset_ids": conflicts})
    entries = []
    for member in memberships:
        asset = assets.get(member["asset_id"])
        if not asset:
            continue
        kind = asset.get("type")
        if kind == "image":
            split = image_splits[asset["id"]]
            if asset["id"] not in selected_images:
                continue
            folder = category_folders[split] if selected_splits else ""
        elif kind == "annotation":
            if not body.include_annotations or not (annotation_targets.get(asset["id"], set()) & selected_images):
                continue
            split_set = annotation_splits.get(asset["id"], set())
            folder = category_folders[next(iter(split_set))] if selected_splits else ""
        else:
            if body.export_type == "current" and asset["id"] not in body.asset_ids:
                continue
            if body.export_type not in {"all", "current"}:
                continue
            folder = ""
        entries.append({"asset_id": asset["id"], "name": asset["name"], "folder": folder})
    if not entries:
        raise AppError(400, "DATASET_EMPTY", "数据集中没有可导出的素材")
    timestamp = now()
    label = {"all": "全部导出", "current": "导出当前", "train": "训练集", "val": "验证集", "test": "测试集", "unassigned": "未划分", "categories": "指定分类（" + "、".join(labels[split] for split in body.splits) + "）"}[body.export_type]
    export_name = body.name or f"{dataset['name']} {dataset.get('current_version') or '未发布'} {label}"
    job = {"id": new_id(), "type": "dataset_export", "name": export_name, "state": "queued", "progress": 0, "owner_id": user["id"], "input": {"asset_ids": [item["asset_id"] for item in entries], "asset_count": len(entries), "dataset_id": dataset_id, "export_type": body.export_type, "include_annotations": body.include_annotations, "entries": entries}, "result": None, "error": None, "created_at": timestamp, "updated_at": timestamp, "expires_at": timestamp + timedelta(hours=settings.export_expiry_hours)}
    await db.jobs.insert_one(job)
    try:
        await asyncio.to_thread(celery_client.send_task, "worker.tasks.build_export", args=[job["id"]])
    except Exception as exc:
        job["state"] = "failed"
        job["error"] = {"code": "TASK_DISPATCH_FAILED", "message": str(exc)[:500]}
        job["updated_at"] = now()
        await db.jobs.update_one({"id": job["id"]}, {"$set": {"state": job["state"], "error": job["error"], "updated_at": job["updated_at"]}})
    await record_audit(actor=user, action="dataset.export_created", object_type="job", object_id=job["id"], request_id=request.state.request_id, changes={"dataset_id": dataset_id, "asset_count": len(entries), "export_type": body.export_type, "include_annotations": body.include_annotations})
    return public_document(job) or {}
