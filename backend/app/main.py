import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from .audit import record_system_audit
from .bootstrap import bootstrap
from .config import get_settings
from .database import db, ping_database
from .errors import AppError, app_error_handler
from .routers import admin, assets, auth, collections, datasets, jobs, relations, system, tags
from .storage import storage
from .utils import new_id

settings = get_settings()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = record.msg if isinstance(record.msg, dict) else {"message": record.getMessage()}
        return json.dumps({"level": record.levelname.lower(), **payload}, ensure_ascii=False, default=str)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
logger = logging.getLogger("cv-archive")
_last_ready_status: bool | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    security_errors = settings.deployment_security_errors()
    if security_errors:
        raise RuntimeError("生产环境配置不安全：" + "；".join(security_errors))
    await bootstrap()
    recovered = await jobs.reconcile_stale_jobs()
    if recovered:
        logger.warning({"event": "stale_jobs_recovered", "count": recovered})
    dispatched = await jobs.dispatch_pending_process_jobs()
    if dispatched:
        logger.warning({"event": "pending_process_jobs_dispatched", "count": dispatched})
    async def cleanup_upload_chunks() -> None:
        while True:
            try:
                removed = await assets.cleanup_expired_upload_chunks()
                if removed:
                    logger.info({"event": "orphan_upload_chunks_removed", "count": removed})
            except Exception as exc:
                logger.warning({"event": "upload_chunk_cleanup_failed", "error": type(exc).__name__})
            await asyncio.sleep(3600)

    async def backfill_export_sizes() -> None:
        while True:
            try:
                result = await jobs.backfill_export_sizes()
                logger.info({"event": "export_sizes_backfilled", **result})
            except Exception as exc:
                logger.warning({"event": "export_size_backfill_failed", "error": type(exc).__name__})
            await asyncio.sleep(3600)

    async def dispatch_pending_upload_jobs() -> None:
        while True:
            try:
                dispatched_count = await jobs.dispatch_pending_process_jobs()
                if dispatched_count:
                    logger.info({"event": "pending_process_jobs_dispatched", "count": dispatched_count})
            except Exception as exc:
                logger.warning({"event": "pending_process_job_dispatch_failed", "error": type(exc).__name__})
            await asyncio.sleep(60)

    async def recover_stale_jobs() -> None:
        while True:
            try:
                recovered_count = await jobs.reconcile_stale_jobs()
                if recovered_count:
                    logger.warning({"event": "stale_jobs_recovered", "count": recovered_count})
                    await record_system_audit(
                        action="job.stale_recovered", request_id=new_id(), object_name="异常后台任务",
                        changes={"count": recovered_count},
                    )
            except Exception as exc:
                logger.warning({"event": "stale_job_recovery_failed", "error": type(exc).__name__})
            await asyncio.sleep(60)

    cleanup_task = asyncio.create_task(cleanup_upload_chunks())
    export_size_task = asyncio.create_task(backfill_export_sizes())
    pending_job_task = asyncio.create_task(dispatch_pending_upload_jobs())
    stale_job_task = asyncio.create_task(recover_stale_jobs())
    try:
        yield
    finally:
        cleanup_task.cancel()
        export_size_task.cancel()
        pending_job_task.cancel()
        stale_job_task.cancel()
        try:
            await asyncio.gather(cleanup_task, export_size_task, pending_job_task, stale_job_task)
        except asyncio.CancelledError:
            pass


app = FastAPI(title="CV Archive API", version="1.6.1", lifespan=lifespan)
app.add_exception_handler(AppError, app_error_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_base_url, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or new_id()
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    client_ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if not client_ip and request.client:
        client_ip = request.client.host
    try:
        await db.audit_logs.update_many(
            {"request_id": request_id},
            {"$set": {
                "request_method": request.method,
                "request_path": request.url.path,
                "response_status": response.status_code,
                "duration_ms": duration_ms,
                "outcome": "success" if response.status_code < 400 else "failed",
                "client_ip": client_ip or "unknown",
                "user_agent": request.headers.get("user-agent", ""),
            }},
        )
    except Exception as exc:
        logger.warning({"event": "audit_request_context_failed", "error": type(exc).__name__})
    event = {
        "event": "http_request",
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "duration_ms": duration_ms,
        "slow": duration_ms >= settings.slow_request_ms,
    }
    (logger.warning if event["slow"] else logger.info)(event)
    return response


@app.get("/health/live", tags=["health"])
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def ready() -> dict[str, object]:
    global _last_ready_status
    checks: dict[str, bool] = {}
    try:
        checks["mongodb"] = await ping_database()
    except Exception as exc:
        checks["mongodb"] = False
        logger.warning({"event": "readiness_check_failed", "dependency": "mongodb", "error": type(exc).__name__})
    try:
        checks["minio"] = await asyncio.to_thread(storage.bucket_exists, settings.minio_bucket)
    except Exception as exc:
        checks["minio"] = False
        logger.warning({"event": "readiness_check_failed", "dependency": "minio", "error": type(exc).__name__})
    redis = None
    try:
        redis = Redis.from_url(settings.redis_url)
        checks["redis"] = bool(await redis.ping())
    except Exception as exc:
        checks["redis"] = False
        logger.warning({"event": "readiness_check_failed", "dependency": "redis", "error": type(exc).__name__})
    finally:
        if redis is not None:
            try:
                await redis.aclose()
            except Exception as exc:
                logger.warning({"event": "readiness_cleanup_failed", "dependency": "redis", "error": type(exc).__name__})
    healthy = all(checks.values())
    if _last_ready_status is not healthy:
        try:
            await record_system_audit(
                action="system.service_recovered" if healthy else "system.service_unavailable",
                request_id=new_id(), object_name="基础服务",
                changes={"checks": checks},
            )
        except Exception as exc:
            logger.warning({"event": "service_state_audit_failed", "error": type(exc).__name__})
        _last_ready_status = healthy
    if not healthy:
        raise AppError(503, "DEPENDENCY_UNAVAILABLE", "一个或多个基础服务不可用", checks)
    return {"status": "ok", "checks": checks}


@app.get("/api/v1/system/health", tags=["health"])
async def system_health() -> dict[str, object]:
    try:
        return await ready()
    except AppError as exc:
        return {"status": "degraded", "checks": exc.details or {}}


app.include_router(auth.router, prefix="/api/v1")
app.include_router(assets.router, prefix="/api/v1")
app.include_router(relations.router, prefix="/api/v1")
app.include_router(collections.router, prefix="/api/v1")
app.include_router(datasets.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(tags.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(system.router, prefix="/api/v1")
