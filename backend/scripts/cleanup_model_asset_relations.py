"""Report and explicitly remove legacy model-to-asset training relations.

Run from backend with its virtual environment. The default mode is read-only.
An apply run requires an absolute backup path outside the repository and the
exact relation count printed by the report. Audit records are never removed.
"""

import argparse
import json
from pathlib import Path

from bson import json_util
from pymongo import MongoClient

from app.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--confirm-count", type=int)
    args = parser.parse_args()
    settings = get_settings()
    client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
    database = client[settings.mongodb_database]
    client.admin.command("ping")
    asset_ids = database.assets.distinct("id")
    query = {"relation_type": "trained_on", "target_id": {"$in": asset_ids}}
    rows = list(database.relations.find(query))
    version_ids = set(database.dataset_versions.distinct("id"))
    linked_pairs = {(row["source_id"], row["target_id"]) for row in database.relations.find({"relation_type": "trained_on", "target_id": {"$in": list(version_ids)}, "status": "active"}, {"source_id": 1, "target_id": 1})}
    def has_version_link(row: dict) -> bool:
        return (row["source_id"], (row.get("provenance") or {}).get("dataset_version_id")) in linked_pairs
    report = {
        "database": settings.mongodb_database,
        "direct_relations": len(rows),
        "active": sum(row.get("status") == "active" for row in rows),
        "matching_version_link": sum(has_version_link(row) for row in rows),
        "without_matching_version_link": sum(not has_version_link(row) for row in rows),
        "ids": [row["id"] for row in rows],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not args.apply:
        return
    if args.confirm_count != len(rows) or args.backup is None or not args.backup.is_absolute():
        parser.error("Apply requires --confirm-count matching the report and an absolute --backup path")
    if args.backup.exists():
        parser.error("Backup path already exists")
    args.backup.parent.mkdir(parents=True, exist_ok=True)
    with args.backup.open("x", encoding="utf-8") as backup:
        for row in rows:
            backup.write(json_util.dumps(row, ensure_ascii=False) + "\n")
        backup.flush()
    if args.backup.stat().st_size == 0 and rows:
        raise RuntimeError("Backup is empty; no relations were removed")
    result = database.relations.delete_many({"id": {"$in": report["ids"]}})
    print(json.dumps({"backed_up": len(rows), "deleted": result.deleted_count, "backup": str(args.backup)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
