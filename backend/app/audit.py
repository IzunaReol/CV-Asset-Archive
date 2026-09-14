from typing import Any

from .database import db
from .utils import new_id, now


async def record_audit(
    *,
    actor: dict[str, Any],
    action: str,
    object_type: str,
    object_id: str,
    request_id: str,
    changes: dict[str, Any] | None = None,
) -> None:
    await db.audit_logs.insert_one(
        {
            "id": new_id(),
            "actor_id": actor["id"],
            "actor_username": actor["username"],
            "action": action,
            "object_type": object_type,
            "object_id": object_id,
            "changes": changes or {},
            "request_id": request_id,
            "created_at": now(),
        }
    )
