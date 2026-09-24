"""Read-only reconciliation report for legacy collections migrated to datasets."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from pymongo import MongoClient


def compare_collection(database: Any, collection: dict[str, Any]) -> dict[str, Any]:
    dataset_id = collection["id"]
    expected_ids = set(collection.get("asset_ids") or [])
    current_ids = set(database.dataset_memberships.distinct("asset_id", {"dataset_id": dataset_id}))
    dataset = database.datasets.find_one({"id": dataset_id}, {"_id": 0})
    result: dict[str, Any] = {
        "collection_id": dataset_id,
        "dataset_exists": dataset is not None,
        "expected_members": len(expected_ids),
        "current_members": len(current_ids),
        "missing_members": sorted(expected_ids - current_ids),
        "unexpected_members": sorted(current_ids - expected_ids),
    }
    if dataset and dataset.get("deleted_at") is not None:
        result["skipped_reason"] = "数据集已删除，历史版本已按删除流程清理"
        return result
    if collection.get("frozen_at") is not None:
        version_id = f"legacy-version-{dataset_id}"
        version = database.dataset_versions.find_one({"id": version_id}, {"_id": 0})
        version_ids = set(
            database.dataset_version_memberships.distinct("asset_id", {"version_id": version_id})
        )
        result.update(
            {
                "version_exists": version is not None,
                "version_members": len(version_ids),
                "missing_version_members": sorted(expected_ids - version_ids),
                "unexpected_version_members": sorted(version_ids - expected_ids),
                "current_version_matches": bool(
                    dataset and dataset.get("current_version_id") == version_id
                ),
            }
        )
    return result


def has_mismatch(item: dict[str, Any]) -> bool:
    if item.get("skipped_reason"):
        return False
    return any(
        (
            not item["dataset_exists"],
            bool(item["missing_members"]),
            bool(item["unexpected_members"]),
            item.get("version_exists") is False,
            bool(item.get("missing_version_members")),
            bool(item.get("unexpected_version_members")),
            item.get("current_version_matches") is False,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="核对旧集合迁移后的数据集、版本和成员")
    parser.add_argument("--database", default=os.getenv("MONGODB_DATABASE", "cv_archive"))
    parser.add_argument("--mongodb-uri", default=os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
    args = parser.parse_args()

    client = MongoClient(args.mongodb_uri, serverSelectionTimeoutMS=5000)
    database = client[args.database]
    reports = [compare_collection(database, row) for row in database.collections.find({}, {"_id": 0})]
    mismatches = [item for item in reports if has_mismatch(item)]
    output = {
        "database": args.database,
        "collections_checked": len(reports),
        "mismatch_count": len(mismatches),
        "status": "ok" if not mismatches else "mismatch",
        "items": reports,
    }
    print(json.dumps(output, ensure_ascii=False, default=str))
    client.close()
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
