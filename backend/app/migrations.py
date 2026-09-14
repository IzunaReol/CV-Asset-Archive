from collections.abc import Awaitable, Callable

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


MIGRATIONS: list[Migration] = [
    (1, "asset and relation defaults", migration_001_asset_defaults),
    (2, "normalize relation creator names", migration_002_relation_creator_names),
    (3, "separate archive and image annotation formats", migration_003_archive_format_types),
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
