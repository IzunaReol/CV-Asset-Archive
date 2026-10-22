"""Read-only references that users should see before deleting or replacing assets."""

from typing import Any

from .database import db

CHUNK_SIZE = 250
DETAIL_LIMIT = 100


async def usage_impact(asset_ids: list[str]) -> dict[str, Any]:
    requested = list(dict.fromkeys(asset_ids))
    details: list[dict[str, Any]] = []
    affected_count = 0

    for offset in range(0, len(requested), CHUNK_SIZE):
        ids = requested[offset:offset + CHUNK_SIZE]
        assets = {
            item["id"]: item async for item in db.assets.find(
                {"id": {"$in": ids}, "archived_at": None},
                {"id": 1, "name": 1, "type": 1},
            )
        }
        current_rows = [item async for item in db.dataset_memberships.find(
            {"asset_id": {"$in": ids}}, {"asset_id": 1, "dataset_id": 1},
        )]
        version_rows = [item async for item in db.dataset_version_memberships.find(
            {"asset_id": {"$in": ids}}, {"asset_id": 1, "version_id": 1},
        )]
        direct_relations = [item async for item in db.relations.find(
            {"status": "active", "$or": [
                {"source_id": {"$in": ids}}, {"target_id": {"$in": ids}},
            ]},
            {"source_id": 1, "target_id": 1, "relation_type": 1},
        )]
        direct_model_rows = [row for row in direct_relations
                             if row.get("relation_type") == "trained_on" and row["source_id"] in ids]
        version_ids = {row["version_id"] for row in version_rows}
        version_ids.update(row["target_id"] for row in direct_model_rows)
        versions = {
            item["id"]: item async for item in db.dataset_versions.find(
                {"id": {"$in": list(version_ids)}},
                {"id": 1, "dataset_id": 1, "version": 1},
            )
        } if version_ids else {}
        dataset_ids = {row["dataset_id"] for row in current_rows}
        dataset_ids.update(item["dataset_id"] for item in versions.values())
        datasets = {
            item["id"]: item async for item in db.datasets.find(
                {"id": {"$in": list(dataset_ids)}, "deleted_at": None},
                {"id": 1, "name": 1},
            )
        } if dataset_ids else {}
        linked_versions = {
            row["version_id"] for row in version_rows if row["version_id"] in versions
        }
        model_links = [item async for item in db.relations.find(
            {"target_id": {"$in": list(linked_versions)},
             "relation_type": "trained_on", "status": "active"},
            {"source_id": 1, "target_id": 1},
        )] if linked_versions else []
        model_ids = {row["source_id"] for row in model_links}
        models = {
            item["id"]: item async for item in db.assets.find(
                {"id": {"$in": list(model_ids)}, "type": "model", "archived_at": None},
                {"id": 1, "name": 1},
            )
        } if model_ids else {}

        for asset_id in ids:
            asset = assets.get(asset_id)
            if not asset:
                continue
            current = {
                row["dataset_id"] for row in current_rows
                if row["asset_id"] == asset_id and row["dataset_id"] in datasets
            }
            history_ids = {
                row["version_id"] for row in version_rows if row["asset_id"] == asset_id
            }
            history_ids.update(
                row["target_id"] for row in direct_model_rows if row["source_id"] == asset_id
            )
            history = [
                versions[version_id] for version_id in history_ids
                if version_id in versions and versions[version_id]["dataset_id"] in datasets
            ]
            related_models = {
                row["source_id"] for row in model_links
                if row["target_id"] in history_ids and row["source_id"] in models
            }
            relation_count = sum(
                row["source_id"] == asset_id or row["target_id"] == asset_id
                for row in direct_relations
            )
            other_relation_count = sum(
                (row["source_id"] == asset_id or row["target_id"] == asset_id)
                and row.get("relation_type") != "trained_on"
                for row in direct_relations
            )
            affected = bool(current or history or related_models or relation_count)
            affected_count += affected
            if affected and len(details) < DETAIL_LIMIT:
                details.append({
                    "id": asset_id,
                    "name": asset.get("name", asset_id),
                    "type": asset.get("type"),
                    "current_datasets": [
                        {"id": key, "name": datasets[key]["name"]} for key in sorted(current)
                    ],
                    "historical_versions": [
                        {"id": item["id"], "version": item["version"],
                         "dataset_id": item["dataset_id"],
                         "dataset_name": datasets[item["dataset_id"]]["name"]}
                        for item in sorted(history, key=lambda value: (value["dataset_id"], value["version"]))
                    ],
                    "models": [
                        {"id": key, "name": models[key]["name"]} for key in sorted(related_models)
                    ],
                    "relation_count": relation_count,
                    "other_relation_count": other_relation_count,
                })

    return {
        "total": len(requested), "affected_count": affected_count,
        "items": details, "details_truncated": affected_count > len(details),
    }
