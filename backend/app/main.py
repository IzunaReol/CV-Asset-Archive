import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from .bootstrap import bootstrap
from .config import get_settings
from .database import ping_database
from .errors import AppError, app_error_handler
from .routers import admin, assets, auth, collections, datasets, jobs, relations, tags
from .storage import storage
from .utils import new_id

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("cv-archive")


@asynccontextmanager
async def lifespan(_: FastAPI):
    security_errors = settings.deployment_security_errors()
    if security_errors:
        raise RuntimeError("生产环境配置不安全：" + "；".join(security_errors))
    await bootstrap()
    recovered = await jobs.reconcile_stale_jobs()
    if recovered:
        logger.warning({"event": "stale_jobs_recovered", "count": recovered})
    yield


app = FastAPI(title="CV Archive API", version="1.3.2", lifespan=lifespan)
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
    logger.info(
        {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    )
    return response


@app.get("/health/live", tags=["health"])
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def ready() -> dict[str, object]:
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
    if not all(checks.values()):
        raise AppError(503, "DEPENDENCY_UNAVAILABLE", "一个或多个基础服务不可用", checks)
    return {"status": "ok", "checks": checks}


app.include_router(auth.router, prefix="/api/v1")
app.include_router(assets.router, prefix="/api/v1")
app.include_router(relations.router, prefix="/api/v1")
app.include_router(collections.router, prefix="/api/v1")
app.include_router(datasets.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(tags.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
