import asyncio
from datetime import timedelta
from typing import Any

from celery import Celery
from fastapi import APIRouter, Query, Request

from ..audit import record_audit
from ..config import get_settings
from ..database import db
from ..dependencies import ReadUser, WriteUser
from ..errors import AppError
from ..schemas import ExportCreate
from ..storage import presigned_get
from ..utils import new_id, now, public_document

router = APIRouter(tags=["jobs"])
settings = get_settings()
celery_client = Celery(broker=settings.redis_url)


@router.post("/exports", status_code=202)
async def create_export(body: ExportCreate, request: Request, user: WriteUser) -> dict[str, Any]:
    if not body.asset_ids and not body.query:
        raise AppError(400, "EXPORT_SELECTION_REQUIRED", "请选择素材或提供筛选条件")
    if body.asset_ids:
        asset_ids = list(dict.fromkeys(body.asset_ids))
    else:
        query = {**(body.query or {}), "archived_at": None}
        asset_ids = [item["id"] async for item in db.assets.find(query, {"id": 1}).limit(100000)]
    if not asset_ids:
        raise AppError(400, "EXPORT_EMPTY", "筛选结果中没有可导出的素材")
    job = {
        "id": new_id(),
        "type": "export",
        "name": body.name,
        "state": "queued",
        "progress": 0,
        "owner_id": user["id"],
        "input": {"asset_ids": asset_ids},
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
    job_type: str | None = Query(None, alias="type"),
) -> dict[str, Any]:
    query = (
        {}
        if "admin" in user["roles"] or "data_manager" in user["roles"]
        else {"owner_id": user["id"]}
    )
    if job_type:
        query["type"] = job_type
    total = await db.jobs.count_documents(query)
    cursor = (
        db.jobs.find(query).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size)
    )
    return {
        "items": [public_document(item) async for item in cursor],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


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
    query: dict[str, Any] = {"id": job_id, "type": "export"}
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
    job = await db.jobs.find_one({"id": job_id, "state": "failed"})
    if job is None:
        raise AppError(409, "JOB_NOT_RETRYABLE", "任务不存在或当前状态不可重试")
    await db.jobs.update_one(
        {"id": job_id},
        {
            "$set": {"state": "queued", "progress": 0, "error": None, "updated_at": now()},
            "$inc": {"attempt": 1},
        },
    )
    if job["type"] == "process_asset":
        await db.assets.update_one(
            {"id": job["input"]["asset_id"]},
            {"$set": {"status": "processing", "processing_error": None, "updated_at": now()}},
        )
    task_name = (
        "worker.tasks.build_export" if job["type"] == "export" else "worker.tasks.process_asset"
    )
    try:
        await asyncio.to_thread(
            celery_client.send_task,
            task_name,
            args=[job_id] + ([job["input"]["asset_id"]] if job["type"] != "export" else []),
        )
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
