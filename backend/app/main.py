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
    await bootstrap()
    yield


app = FastAPI(title="CV Archive API", version="1.2.1", lifespan=lifespan)
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
        checks["minio"] = await asyncio.to_thread(storage.bucket_exists, settings.minio_bucket)
        redis = Redis.from_url(settings.redis_url)
        checks["redis"] = bool(await redis.ping())
        await redis.aclose()
    except Exception:
        checks.setdefault("mongodb", False)
        checks.setdefault("minio", False)
        checks.setdefault("redis", False)
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
