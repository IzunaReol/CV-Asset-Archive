import asyncio

from .config import get_settings
from .database import db, ensure_indexes
from .migrations import run_migrations
from .schemas import Role
from .security import hash_password
from .storage import ensure_bucket
from .utils import new_id, now

settings = get_settings()

DEFAULT_TAGS = [
    ("status", "状态", ["待整理", "未标注", "已标注", "审核中", "待复核", "已训练"], "#d95c35"),
    ("project", "项目", [], "#2764c6"),
    ("algorithm", "所属算法", [], "#7c3aed"),
    ("scene", "场景", ["室内", "室外", "夜间", "车内"], "#0891b2"),
    ("lighting", "光照", ["强", "中", "弱"], "#ca8a04"),
    ("annotation_format", "标注格式", ["COCO", "YOLO", "VOC"], "#16a34a"),
    ("model_framework", "模型框架", ["YOLO11", "YOLOv8", "RT-DETR"], "#475569"),
    ("model_version", "模型版本", [], "#64748b"),
]

DEFAULT_FORMATS = {
    "image": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".avif"],
    "video": [".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mpeg", ".mpg", ".ts", ".mts", ".m2ts"],
    "annotation": [".txt", ".xml", ".json", ".yaml", ".yml", ".csv"],
    "model": [".pt", ".pth", ".onnx", ".engine", ".weights", ".ckpt", ".pb", ".tflite", ".torchscript", ".safetensors", ".mlmodel", ".bin"],
    "archive": [".rar", ".zip", ".7z"],
    "image_annotation": [".rar", ".zip", ".7z"],
}


async def bootstrap() -> None:
    await run_migrations()
    await ensure_indexes()
    if await db.users.count_documents({}) == 0:
        await db.users.insert_one(
            {
                "id": new_id(),
                "username": settings.initial_admin_username,
                "password_hash": hash_password(settings.initial_admin_password),
                "roles": [Role.ADMIN.value],
                "status": "active",
                "must_change_password": False,
                "created_at": now(),
                "updated_at": now(),
            }
        )
    for key, name, values, color in DEFAULT_TAGS:
        await db.tag_definitions.update_one(
            {"key": key},
            {
                "$setOnInsert": {
                    "id": new_id(),
                    "key": key,
                    "name": name,
                    "values": values,
                    "color": color,
                    "asset_types": [],
                    "free_input": not bool(values),
                    "created_at": now(),
                }
            },
            upsert=True,
        )
    for asset_type, extensions in DEFAULT_FORMATS.items():
        await db.format_definitions.update_one(
            {"asset_type": asset_type},
            {"$set": {"built_in": True, "protected_extensions": extensions}, "$setOnInsert": {"id": new_id(), "asset_type": asset_type, "remark": "", "extensions": extensions, "created_at": now(), "updated_at": now()}},
            upsert=True,
        )
    await db.format_definitions.delete_one({"asset_type": "other"})
    await asyncio.to_thread(ensure_bucket)
