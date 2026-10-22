from datetime import timedelta
from typing import Any

from .config import get_settings
from .database import db
from .utils import new_id, now

AUDIT_OBJECT_SOURCES = {
    "asset": ("assets", "name"),
    "dataset": ("datasets", "name"),
    "dataset_version": ("dataset_versions", "version"),
    "job": ("jobs", "name"),
    "user": ("users", "username"),
    "role_template": ("role_templates", "name"),
    "tag_definition": ("tag_definitions", "name"),
    "format_definition": ("format_definitions", "asset_type"),
    "metric_definition": ("metric_definitions", "name"),
    "metric_category": ("metric_categories", "name"),
    "collection": ("collections", "name"),
    "saved_view": ("saved_views", "name"),
}
settings = get_settings()


async def resolve_audit_object_name(
    object_type: str,
    object_id: str,
    changes: dict[str, Any] | None = None,
) -> str:
    changes = changes or {}
    if object_id == "batch":
        count = changes.get("count") or len(changes.get("asset_ids") or [])
        return f"批量素材（{count} 项）" if count else "批量素材"
    if object_type == "relation":
        return "关联关系记录"
    source = AUDIT_OBJECT_SOURCES.get(object_type)
    if source:
        collection_name, name_field = source
        collection = getattr(db, collection_name)
        query = {"asset_type": object_id} if object_type == "format_definition" else {"id": object_id}
        document = await collection.find_one(query, {name_field: 1})
        if document and document.get(name_field):
            return str(document[name_field])
    return str(changes.get("filename") or changes.get("name") or "未命名对象")


async def record_audit(
    *,
    actor: dict[str, Any],
    action: str,
    object_type: str,
    object_id: str,
    request_id: str,
    changes: dict[str, Any] | None = None,
    object_name: str | None = None,
) -> None:
    change_details = changes or {}
    created_at = now()
    await db.audit_logs.insert_one(
        {
            "id": new_id(),
            "actor_id": actor["id"],
            "actor_username": actor["username"],
            "action": action,
            "object_type": object_type,
            "object_id": object_id,
            "object_name": object_name or await resolve_audit_object_name(
                object_type, object_id, change_details
            ),
            "changes": change_details,
            "request_id": request_id,
            "created_at": created_at,
            "expires_at": created_at + timedelta(days=settings.audit_log_retention_days),
        }
    )


async def record_system_audit(
    *, action: str, request_id: str, object_name: str, changes: dict[str, Any] | None = None,
    actor: dict[str, Any] | None = None,
) -> None:
    """Record security and availability events that may not have an authenticated actor."""
    created_at = now()
    await db.audit_logs.insert_one({
        "id": new_id(),
        "actor_id": (actor or {}).get("id", "system"),
        "actor_username": (actor or {}).get("username", "系统"),
        "action": action,
        "object_type": "system",
        "object_id": action,
        "object_name": object_name,
        "changes": changes or {},
        "request_id": request_id,
        "created_at": created_at,
        "expires_at": created_at + timedelta(days=settings.audit_log_retention_days),
    })
