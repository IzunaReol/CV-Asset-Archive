from typing import Any

from .utils import public_document

DATASET_WRITE_BATCH_SIZE = 1000
DATASET_COMPARE_DETAIL_LIMIT = 1000


async def cursor_batches(cursor, size: int = DATASET_WRITE_BATCH_SIZE):
    batch = []
    async for item in cursor:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


async def compare_version_memberships(
    database: Any, from_version_id: str, to_version_id: str, detail_limit: int
) -> dict[str, Any]:
    before_cursor = database.dataset_version_memberships.find(
        {"version_id": from_version_id}
    ).sort("asset_id", 1)
    after_cursor = database.dataset_version_memberships.find(
        {"version_id": to_version_id}
    ).sort("asset_id", 1)
    before = await anext(before_cursor, None)
    after = await anext(after_cursor, None)
    added, removed, changed = [], [], []
    counts = {"added": 0, "removed": 0, "unchanged": 0, "changed": 0}
    returned = 0
    while before is not None or after is not None:
        before_id = before["asset_id"] if before is not None else None
        after_id = after["asset_id"] if after is not None else None
        if before is None or (after is not None and after_id < before_id):
            counts["added"] += 1
            if returned < detail_limit:
                added.append(after)
                returned += 1
            after = await anext(after_cursor, None)
        elif after is None or before_id < after_id:
            counts["removed"] += 1
            if returned < detail_limit:
                removed.append(before)
                returned += 1
            before = await anext(before_cursor, None)
        else:
            if before["snapshot"] == after["snapshot"]:
                counts["unchanged"] += 1
            else:
                counts["changed"] += 1
                if returned < detail_limit:
                    changed.append({
                        "asset_id": before_id,
                        "before": before["snapshot"],
                        "after": after["snapshot"],
                    })
                    returned += 1
            before = await anext(before_cursor, None)
            after = await anext(after_cursor, None)
    counts["total_changed"] = counts["added"] + counts["removed"] + counts["changed"]
    return {
        "added": [public_document(item) for item in added],
        "removed": [public_document(item) for item in removed],
        "unchanged": [],
        "changed": changed,
        "counts": counts,
        "truncated": counts["total_changed"] > returned,
        "detail_limit": detail_limit,
    }
