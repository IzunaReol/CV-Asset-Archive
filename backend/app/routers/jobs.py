import asyncio
from datetime import datetime, timedelta
from typing import Any

from celery import Celery
from fastapi import APIRouter, Query, Request

from ..audit import record_audit
from ..config import get_settings
from ..database import db
from ..dependencies import ManageUser, ReadUser, WriteUser
from ..errors import AppError
from ..schemas import ExportCreate, JobState, VisibleJobType
from ..storage import presigned_get, stat_object
from ..utils import new_id, now, public_document
from .assets import resolve_selection_ids

router = APIRouter(tags=["jobs"])
settings = get_settings()
celery_client = Celery(broker=settings.redis_url)

TASK_NAMES = {
    "process_asset": "worker.tasks.process_asset",
    "export": "worker.tasks.build_export",
    "dataset_export": "worker.tasks.build_export",
    "trash_empty": "worker.tasks.empty_trash",
}
CANCELLABLE_JOB_TYPES = {"export", "dataset_export"}


async def _backfill_export_size(job: dict[str, Any], semaphore: asyncio.Semaphore) -> dict[str, Any]:
    result = job.get("result")
    if (
        job.get("state") != "succeeded"
        or job.get("type") not in CANCELLABLE_JOB_TYPES
        or not isinstance(result, dict)
        or result.get("size") is not None
        or not result.get("object_key")
    ):
        return {"job_id": job.get("id"), "succeeded": False, "skipped": True}
    async with semaphore:
        try:
            obj = await asyncio.to_thread(stat_object, result["object_key"])
            size = int(obj.size)
            if size < 0:
                raise ValueError("对象大小无效")
            updated = await db.jobs.update_one(
                {"id": job["id"], "result.size": {"$exists": False}},
                {"$set": {"result.size": size}},
            )
            return {"job_id": job["id"], "succeeded": True, "updated": bool(updated.modified_count), "size": size}
        except Exception as exc:  # noqa: BLE001 - one unavailable object must not stop the batch
            try:
                await db.jobs.update_one(
                    {"id": job.get("id")},
                    {"$set": {
                        "result.size_backfill_checked_at": now(),
                        "result.size_backfill_last_error": f"{type(exc).__name__}: {str(exc)[:300]}",
                    }},
                )
            except Exception:  # noqa: BLE001 - report the original failure and retry next cycle
                pass
            return {"job_id": job.get("id"), "succeeded": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}


async def backfill_export_sizes(limit: int = 100) -> dict[str, Any]:
    started_at = now()
    cursor = db.jobs.find(
        {
            "type": {"$in": sorted(CANCELLABLE_JOB_TYPES)},
            "state": "succeeded",
            "result.object_key": {"$exists": True},
            "result.size": {"$exists": False},
        }
    ).sort([("result.size_backfill_checked_at", 1), ("created_at", 1)]).limit(limit)
    pending = [item async for item in cursor]
    semaphore = asyncio.Semaphore(8)
    results = await asyncio.gather(*(_backfill_export_size(item, semaphore) for item in pending))
    failures = [
        {"job_id": item.get("job_id"), "error": item["error"]}
        for item in results if item.get("error")
    ]
    summary = {
        "type": "export_size_backfill",
        "processed": len(pending),
        "succeeded": sum(1 for item in results if item.get("succeeded")),
        "failed": len(failures),
        "started_at": started_at,
        "last_run_at": now(),
        "failures": failures[:100],
    }
    maintenance_runs = getattr(db, "maintenance_runs", None)
    if maintenance_runs is not None:
        try:
            await maintenance_runs.insert_one(dict(summary))
        except Exception:  # noqa: BLE001 - status persistence must not discard completed repairs
            pass
    return summary


def _job_task_args(job: dict[str, Any]) -> list[str]:
    if job["type"] == "process_asset":
        return [job["id"], job["input"]["asset_id"]]
    return [job["id"]]


async def _dispatch_job(job: dict[str, Any]) -> None:
    task_name = TASK_NAMES.get(job["type"])
    if task_name is None:
        raise AppError(409, "JOB_TYPE_NOT_RETRYABLE", "该任务类型不支持重新提交")
    await asyncio.to_thread(celery_client.send_task, task_name, args=_job_task_args(job))


async def reconcile_stale_jobs() -> int:
    cutoff = now() - timedelta(minutes=settings.job_stale_minutes)
    stale = await db.jobs.find(
        {"state": "running", "updated_at": {"$lt": cutoff}},
        {"id": 1, "type": 1, "input": 1},
    ).to_list(length=None)
    if not stale:
        return 0
    stale_ids = [item["id"] for item in stale]
    timestamp = now()
    await db.jobs.update_many(
        {"id": {"$in": stale_ids}, "state": "running"},
        {
            "$set": {
                "state": "failed",
                "error": {
                    "code": "TASK_INTERRUPTED",
                    "message": "服务异常中断，任务未正常结束，可重新提交",
                },
                "updated_at": timestamp,
            }
        },
    )
    asset_ids = [
        item.get("input", {}).get("asset_id")
        for item in stale
        if item.get("type") == "process_asset" and item.get("input", {}).get("asset_id")
    ]
    if asset_ids:
        await db.assets.update_many(
            {"id": {"$in": asset_ids}, "status": "processing"},
            {
                "$set": {
                    "status": "failed",
                    "processing_error": {
                        "code": "TASK_INTERRUPTED",
                        "message": "服务异常中断，素材处理未正常结束",
                    },
                    "updated_at": timestamp,
                }
            },
        )
    return len(stale_ids)


@router.post("/exports", status_code=202)
async def create_export(body: ExportCreate, request: Request, user: WriteUser) -> dict[str, Any]:
    asset_ids = await resolve_selection_ids(user, body.asset_ids, body.selection_id, body.excluded_ids)
    if not asset_ids:
        raise AppError(400, "EXPORT_EMPTY", "筛选结果中没有可导出的素材")
    if body.selection_id:
        await db.asset_selection_sets.update_one(
            {"id": body.selection_id, "owner_id": user["id"]},
            {"$set": {"expires_at": now() + timedelta(hours=settings.export_expiry_hours)}},
        )
        job_input = {
            "selection_id": body.selection_id,
            "excluded_ids": body.excluded_ids,
            "asset_count": len(asset_ids),
        }
    else:
        job_input = {"asset_ids": asset_ids, "asset_count": len(asset_ids)}
    job = {
        "id": new_id(),
        "type": "export",
        "name": body.name,
        "state": "queued",
        "progress": 0,
        "owner_id": user["id"],
        "input": job_input,
        "result": None,
        "error": None,
        "created_at": now(),
        "updated_at": now(),
        "expires_at": now() + timedelta(hours=settings.export_expiry_hours),
    }
    await db.jobs.insert_one(job)
    try:
        await asyncio.to_thread(
            celery_client.send_task, "worker.tasks.build_export", args=[job["id"]]
        )
    except Exception as exc:
        job["state"] = "failed"
        job["error"] = {"code": "TASK_DISPATCH_FAILED", "message": str(exc)[:500]}
        job["updated_at"] = now()
        await db.jobs.update_one(
            {"id": job["id"]},
            {
                "$set": {
                    "state": job["state"],
                    "error": job["error"],
                    "updated_at": job["updated_at"],
                }
            },
        )
    await record_audit(
        actor=user,
        action="export.created",
        object_type="job",
        object_id=job["id"],
        request_id=request.state.request_id,
        changes={"asset_count": len(asset_ids)},
    )
    return public_document(job) or {}


@router.get("/jobs")
async def list_jobs(
    user: ReadUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    job_type: VisibleJobType | None = Query(None, alias="type"),
    state: JobState | None = Query(None),
    created_from: datetime | None = Query(None),
    created_to: datetime | None = Query(None),
    download_only: bool = Query(False),
) -> dict[str, Any]:
    query = (
        {}
        if "admin" in user["roles"] or "data_manager" in user["roles"]
        else {"owner_id": user["id"]}
    )
    visible_job_types = ["export", "dataset_export", "trash_empty"]
    if download_only:
        query["type"] = {"$in": ["export", "dataset_export"]}
    elif job_type:
        query["type"] = getattr(job_type, "value", job_type)
    else:
        query["type"] = {"$in": visible_job_types}
    if state:
        query["state"] = getattr(state, "value", state)
    if created_from and created_to and created_from > created_to:
        raise AppError(400, "INVALID_TIME_RANGE", "开始时间不能晚于结束时间")
    if created_from or created_to:
        query["created_at"] = {}
        if created_from:
            query["created_at"]["$gte"] = created_from
        if created_to:
            query["created_at"]["$lte"] = created_to
    total = await db.jobs.count_documents(query)
    cursor = (
        db.jobs.find(query).sort([("created_at", -1), ("id", -1)]).skip((page - 1) * page_size).limit(page_size)
    )
    jobs = [item async for item in cursor]
    return {
        "items": [public_document(item) for item in jobs],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/jobs/maintenance/export-size-backfill")
async def export_size_backfill_status(user: ManageUser) -> dict[str, Any]:
    run = await db.maintenance_runs.find_one(
        {"type": "export_size_backfill"},
        sort=[("last_run_at", -1)],
    )
    if run is None:
        return {"processed": 0, "succeeded": 0, "failed": 0, "last_run_at": None, "failures": []}
    return public_document(run) or {}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, user: ReadUser) -> dict[str, Any]:
    query: dict[str, Any] = {"id": job_id}
    if not ({"admin", "data_manager"} & set(user["roles"])):
        query["owner_id"] = user["id"]
    job = await db.jobs.find_one(query)
    if job is None:
        raise AppError(404, "JOB_NOT_FOUND", "任务不存在")
    return public_document(job) or {}


@router.get("/exports/{job_id}/download-url")
async def export_download_url(job_id: str, user: ReadUser) -> dict[str, Any]:
    query: dict[str, Any] = {"id": job_id, "type": {"$in": ["export", "dataset_export"]}}
    if not ({"admin", "data_manager"} & set(user["roles"])):
        query["owner_id"] = user["id"]
    job = await db.jobs.find_one(query)
    if job is None:
        raise AppError(404, "JOB_NOT_FOUND", "导出任务不存在")
    if job["expires_at"] <= now():
        raise AppError(410, "EXPORT_EXPIRED", "下载文件已过期")
    if job["state"] != "succeeded":
        raise AppError(409, "EXPORT_NOT_READY", "导出任务尚未完成")
    url = await asyncio.to_thread(
        presigned_get, job["result"]["object_key"], 1, f"{job['name']}.zip"
    )
    return {"download_url": url, "expires_in_seconds": 3600}


@router.post("/jobs/{job_id}/retry", status_code=202)
async def retry_job(job_id: str, user: WriteUser) -> dict[str, Any]:
    query: dict[str, Any] = {"id": job_id, "state": "failed"}
    if not ({"admin", "data_manager"} & set(user["roles"])):
        query["owner_id"] = user["id"]
    job = await db.jobs.find_one(query)
    if job is None:
        raise AppError(409, "JOB_NOT_RETRYABLE", "任务不存在或当前状态不可重试")
    if job["type"] not in TASK_NAMES:
        raise AppError(409, "JOB_TYPE_NOT_RETRYABLE", "该任务类型不支持重新提交")
    claimed = await db.jobs.update_one(
        query,
        {
            "$set": {"state": "queued", "progress": 0, "error": None, "updated_at": now()},
            "$inc": {"attempt": 1},
        },
    )
    if not claimed.modified_count:
        raise AppError(409, "JOB_NOT_RETRYABLE", "任务状态已变化，请刷新后重试")
    if job["type"] == "process_asset":
        await db.assets.update_one(
            {"id": job["input"]["asset_id"]},
            {"$set": {"status": "processing", "processing_error": None, "updated_at": now()}},
        )
    try:
        await _dispatch_job(job)
    except Exception as exc:
        await db.jobs.update_one(
            {"id": job_id},
            {
                "$set": {
                    "state": "failed",
                    "error": {"code": "TASK_DISPATCH_FAILED", "message": str(exc)[:500]},
                    "updated_at": now(),
                }
            },
        )
        if job["type"] == "process_asset":
            await db.assets.update_one(
                {"id": job["input"]["asset_id"]},
                {
                    "$set": {
                        "status": "failed",
                        "processing_error": {
                            "code": "TASK_DISPATCH_FAILED",
                            "message": "后台任务提交失败",
                        },
                        "updated_at": now(),
                    }
                },
            )
    return public_document(await db.jobs.find_one({"id": job_id})) or {}


@router.post("/jobs/{job_id}/cancel", status_code=202)
async def cancel_job(job_id: str, request: Request, user: WriteUser) -> dict[str, Any]:
    query: dict[str, Any] = {
        "id": job_id,
        "type": {"$in": sorted(CANCELLABLE_JOB_TYPES)},
        "state": {"$in": ["queued", "running"]},
    }
    if not ({"admin", "data_manager"} & set(user["roles"])):
        query["owner_id"] = user["id"]
    timestamp = now()
    result = await db.jobs.update_one(
        query,
        {
            "$set": {
                "state": "cancelled",
                "cancel_requested": True,
                "cancelled_at": timestamp,
                "cancelled_by": user["id"],
                "updated_at": timestamp,
            }
        },
    )
    if not result.modified_count:
        raise AppError(409, "JOB_NOT_CANCELLABLE", "任务不存在、已结束或不支持取消")
    await record_audit(
        actor=user,
        action="job.cancelled",
        object_type="job",
        object_id=job_id,
        request_id=request.state.request_id,
        changes={},
    )
    return public_document(await db.jobs.find_one({"id": job_id})) or {}
