from typing import Any

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient

from .config import get_settings

settings = get_settings()
client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.mongodb_uri, tz_aware=True)
db = client[settings.mongodb_database]


async def ensure_indexes() -> None:
    await db.users.create_index("username", unique=True)
    await db.refresh_sessions.create_index("token_hash", unique=True)
    await db.refresh_sessions.create_index("expires_at", expireAfterSeconds=0)
    await db.assets.create_index([("sha256", ASCENDING), ("size", ASCENDING)])
    await db.assets.create_index([("archived_at", ASCENDING), ("created_at", DESCENDING)])
    await db.assets.create_index([("name", "text"), ("project", "text")])
    await db.relations.create_index(
        [
            ("source_id", ASCENDING),
            ("target_id", ASCENDING),
            ("relation_type", ASCENDING),
            ("revision", ASCENDING),
        ],
        unique=True,
    )
    await db.relations.create_index([("status", ASCENDING), ("created_at", DESCENDING)])
    await db.collections.create_index([("name", ASCENDING), ("revision", ASCENDING)], unique=True)
    await db.datasets.create_index([("name", ASCENDING)], unique=True)
    await db.datasets.create_index([("status", ASCENDING), ("updated_at", DESCENDING)])
    await db.dataset_memberships.create_index(
        [("dataset_id", ASCENDING), ("asset_id", ASCENDING)], unique=True
    )
    await db.dataset_memberships.create_index([("asset_id", ASCENDING)])
    await db.dataset_versions.create_index(
        [("dataset_id", ASCENDING), ("version_number", ASCENDING)], unique=True
    )
    await db.dataset_versions.create_index([("dataset_id", ASCENDING), ("created_at", DESCENDING)])
    await db.dataset_version_memberships.create_index(
        [("version_id", ASCENDING), ("asset_id", ASCENDING)], unique=True
    )
    await db.jobs.create_index([("owner_id", ASCENDING), ("created_at", DESCENDING)])
    await db.jobs.create_index("expires_at", expireAfterSeconds=0)
    await db.tag_definitions.create_index("key", unique=True)
    await db.audit_logs.create_index([("created_at", DESCENDING)])


async def ping_database() -> bool:
    await client.admin.command("ping")
    return True
