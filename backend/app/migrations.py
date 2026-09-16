from collections.abc import Awaitable, Callable
import hashlib
import json

from .database import db
from .utils import now

Migration = tuple[int, str, Callable[[], Awaitable[None]]]


async def migration_001_asset_defaults() -> None:
    await db.assets.update_many(
        {"archived_at": {"$exists": False}}, {"$set": {"archived_at": None}}
    )


async def migration_002_relation_creator_names() -> None:
    user_ids: list[str] = []
    async for user in db.users.find({}, {"id": 1, "username": 1}):
        user_ids.append(user["id"])
        await db.relations.update_many(
            {"created_by": user["id"]}, {"$set": {"created_by_name": user["username"]}}
        )
    await db.relations.update_many(
        {"created_by": {"$nin": user_ids}}, {"$set": {"created_by_name": "未知用户"}}
    )
    await db.relations.update_many(
        {"status": {"$exists": False}}, {"$set": {"status": "active", "revision": 1}}
    )


async def migration_003_archive_format_types() -> None:
    await db.format_definitions.update_one(
        {"asset_type": "annotation"},
        {"$pull": {"extensions": ".zip", "protected_extensions": ".zip"}},
    )


async def migration_004_collections_to_datasets() -> None:
    async for collection in db.collections.find({}):
        dataset_id = collection["id"]
        created_at = collection.get("created_at") or now()
        await db.datasets.update_one(
            {"id": dataset_id},
            {
                "$setOnInsert": {
                    "id": dataset_id,
                    "name": collection.get("name", "未命名数据集"),
                    "remark": collection.get("description", ""),
                    "status": "待整理",
                    "current_version_id": None,
                    "current_version": None,
                    "created_by": collection.get("created_by"),
                    "created_by_name": "未知用户",
                    "created_at": created_at,
                    "updated_at": collection.get("updated_at") or created_at,
                    "deleted_at": None,
                    "legacy_collection_id": dataset_id,
                }
            },
            upsert=True,
        )
        asset_ids = list(dict.fromkeys(collection.get("asset_ids") or []))
        for asset_id in asset_ids:
            await db.dataset_memberships.update_one(
                {"dataset_id": dataset_id, "asset_id": asset_id},
                {
                    "$setOnInsert": {
                        "id": f"legacy-{dataset_id}-{asset_id}",
                        "dataset_id": dataset_id,
                        "asset_id": asset_id,
                        "created_by": collection.get("created_by"),
                        "created_at": created_at,
                    }
                },
                upsert=True,
            )
        if collection.get("frozen_at") is None:
            continue
        version_id = f"legacy-version-{dataset_id}"
        assets = (
            await db.assets.find({"id": {"$in": asset_ids}})
            .sort("id", 1)
            .to_list(length=len(asset_ids))
            if asset_ids
            else []
        )
        snapshots = []
        for asset in assets:
            snapshot = {
                "name": asset.get("name", ""),
                "type": asset.get("type", "other"),
                "size": int(asset.get("size") or 0),
                "sha256": asset.get("sha256"),
                "tags": asset.get("tags") or {},
                "remark": asset.get("remark") or "",
                "updated_at": asset.get("updated_at"),
            }
            snapshots.append({"asset_id": asset["id"], "snapshot": snapshot})
            await db.dataset_version_memberships.update_one(
                {"version_id": version_id, "asset_id": asset["id"]},
                {"$setOnInsert": {"id": f"legacy-{version_id}-{asset['id']}", "version_id": version_id, "dataset_id": dataset_id, "asset_id": asset["id"], "snapshot": snapshot}},
                upsert=True,
            )
        digest = hashlib.sha256(
            json.dumps(snapshots, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()
        await db.dataset_versions.update_one(
            {"id": version_id},
            {"$setOnInsert": {"id": version_id, "dataset_id": dataset_id, "name": f"{collection.get('name', '数据集')} v1", "kind": "dataset_version", "version": "v1", "version_number": 1, "release_note": "由历史冻结集合迁移", "member_count": len(snapshots), "total_size": sum(item["snapshot"]["size"] for item in snapshots), "content_digest": digest, "created_by": collection.get("created_by"), "created_by_name": "未知用户", "created_at": collection.get("frozen_at") or created_at}},
            upsert=True,
        )
        await db.datasets.update_one(
            {"id": dataset_id},
            {"$set": {"current_version_id": version_id, "current_version": "v1"}},
        )


MIGRATIONS: list[Migration] = [
    (1, "asset and relation defaults", migration_001_asset_defaults),
    (2, "normalize relation creator names", migration_002_relation_creator_names),
    (3, "separate archive and image annotation formats", migration_003_archive_format_types),
    (4, "migrate collections to dataset memberships", migration_004_collections_to_datasets),
]


async def run_migrations() -> None:
    applied = {item["version"] async for item in db.schema_migrations.find({}, {"version": 1})}
    for version, name, migration in MIGRATIONS:
        if version in applied:
            continue
        await migration()
        await db.schema_migrations.insert_one(
            {"version": version, "name": name, "applied_at": now()}
        )
