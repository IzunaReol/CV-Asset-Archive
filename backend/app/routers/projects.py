from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query

from ..database import db
from ..dependencies import ProjectOverviewReadUser
from ..errors import AppError
from ..permissions import effective_menu_permissions

router = APIRouter(prefix="/projects", tags=["projects"])
FILE_PREVIEW_LIMIT = 50


def _asset_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {key: 0 for key in ("image", "video", "annotation", "archive", "other")}
    for row in rows:
        key = row["_id"]["type"]
        counts[key if key in counts else "other"] += row["count"]
    return counts


def _tag_values(asset: dict[str, Any], key: str) -> set[str]:
    value = (asset.get("tags") or {}).get(key, [])
    return set(value if isinstance(value, list) else [value])


def _created_timestamp(value: Any) -> float:
    if not value:
        return float("-inf")
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


@router.get("/overview")
async def project_overview(
    user: ProjectOverviewReadUser,
    projects: list[str] = Query(default=[]),
) -> dict[str, Any]:
    definition = await db.tag_definitions.find_one({"key": "project"})
    available = list(dict.fromkeys((definition or {}).get("values", [])))
    if len(projects) > 50 or any(value not in available for value in projects):
        raise AppError(400, "PROJECT_FILTER_INVALID", "所选项目不在标签管理的可选值中")
    selected = list(dict.fromkeys(projects)) if projects else available
    menus = effective_menu_permissions(user)
    result: dict[str, Any] = {
        "available_projects": available, "selected_projects": selected,
        "summary": {"project_count": len(selected), "dataset_count": 0, "model_count": 0, "file_count": 0},
        "projects": [],
    }
    if not selected:
        return result

    datasets = []
    dataset_by_id: dict[str, dict[str, Any]] = {}
    counts_by_dataset: dict[str, dict[str, int]] = {}
    if "datasets" in menus:
        datasets = await db.datasets.find(
            {"deleted_at": None, "projects": {"$in": selected}},
            {"_id": 0, "id": 1, "name": 1, "projects": 1,
             "current_version": 1, "updated_at": 1},
        ).to_list(length=None)
        dataset_by_id = {item["id"]: item for item in datasets}
        result["summary"]["dataset_count"] = len(datasets)
        if dataset_by_id:
            grouped_cursor = await db.dataset_memberships.aggregate([
                {"$match": {"dataset_id": {"$in": list(dataset_by_id)}}},
                {"$lookup": {"from": "assets", "localField": "asset_id", "foreignField": "id", "as": "asset"}},
                {"$unwind": "$asset"},
                {"$match": {"asset.archived_at": None}},
                {"$group": {"_id": {"dataset_id": "$dataset_id", "type": "$asset.type"}, "count": {"$sum": 1}}},
            ])
            grouped = await grouped_cursor.to_list(length=None)
            for row in grouped:
                dataset_id = row["_id"]["dataset_id"]
                counts = counts_by_dataset.setdefault(dataset_id, _asset_counts([]))
                asset_type = row["_id"]["type"]
                counts[asset_type if asset_type in counts else "other"] += row["count"]
    datasets_by_project: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for dataset in datasets:
        for project in set(dataset.get("projects") or []).intersection(selected):
            datasets_by_project[project].append(dataset)

    model_by_id: dict[str, dict[str, Any]] = {}
    model_project_sources: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    model_project_versions: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    model_project_latest_version: dict[str, dict[str, float]] = defaultdict(dict)
    if "library" in menus:
        direct_models = await db.assets.find(
            {"archived_at": None, "type": "model", "tags.project": {"$in": selected}},
            {"_id": 0, "id": 1, "name": 1, "remark": 1, "tags": 1, "updated_at": 1, "metric_values": 1},
        ).to_list(length=None)
        model_by_id.update({item["id"]: item for item in direct_models})
        for model in direct_models:
            for project in _tag_values(model, "project").intersection(selected):
                model_project_sources[project][model["id"]].add("项目标签")

        if dataset_by_id:
            versions = await db.dataset_versions.find(
                {"dataset_id": {"$in": list(dataset_by_id)}},
                {"_id": 0, "id": 1, "dataset_id": 1, "version": 1, "created_at": 1},
            ).to_list(length=None)
            version_by_id = {item["id"]: item for item in versions}
            if version_by_id:
                relations = await db.relations.find(
                    {"target_id": {"$in": list(version_by_id)}, "relation_type": "trained_on", "status": "active"},
                    {"_id": 0, "source_id": 1, "target_id": 1},
                ).to_list(length=None)
                linked_ids = {row["source_id"] for row in relations}
                if linked_ids:
                    linked_models = await db.assets.find(
                        {"id": {"$in": list(linked_ids)}, "type": "model", "archived_at": None},
                        {"_id": 0, "id": 1, "name": 1, "remark": 1, "tags": 1, "updated_at": 1, "metric_values": 1},
                    ).to_list(length=None)
                    model_by_id.update({item["id"]: item for item in linked_models})
                for relation in relations:
                    model_id = relation["source_id"]
                    if model_id not in model_by_id:
                        continue
                    version = version_by_id[relation["target_id"]]
                    dataset = dataset_by_id[version["dataset_id"]]
                    for project in set(dataset.get("projects") or []).intersection(selected):
                        model_project_sources[project][model_id].add("数据集关联")
                        model_project_versions[project][model_id].add(f"{dataset['name']} · {version['version']}")
                        created_at = _created_timestamp(version.get("created_at"))
                        if created_at != float("-inf"):
                            model_project_latest_version[project][model_id] = max(
                                model_project_latest_version[project].get(model_id, float("-inf")), created_at
                            )
        metric_ids = {
            metric_id
            for asset in model_by_id.values()
            for metric_id, value in (asset.get("metric_values") or {}).items()
            if value is not None and str(value).strip()
        }
        metric_definitions = {
            item["id"]: item
            for item in (
                await db.metric_definitions.find({"id": {"$in": list(metric_ids)}}).to_list(length=len(metric_ids))
                if metric_ids else []
            )
        }
        result["summary"]["model_count"] = len({model_id for rows in model_project_sources.values() for model_id in rows})
        result["summary"]["file_count"] = await db.assets.count_documents(
            {"archived_at": None, "type": {"$ne": "model"}, "tags.project": {"$in": selected}}
        )

    file_stats_by_project: dict[str, list[dict[str, Any]]] = defaultdict(list)
    file_previews_by_project: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if "library" in menus:
        file_cursor = await db.assets.aggregate([
            {"$match": {"archived_at": None, "type": {"$ne": "model"}, "tags.project": {"$in": selected}}},
            {"$set": {"_projects": {"$setUnion": [{"$cond": [
                {"$isArray": "$tags.project"}, "$tags.project", ["$tags.project"],
            ]}, []]}}},
            {"$unwind": "$_projects"},
            {"$match": {"_projects": {"$in": selected}}},
            {"$facet": {
                "counts": [{"$group": {"_id": {"project": "$_projects", "type": "$type"}, "count": {"$sum": 1}}}],
                "previews": [{"$group": {
                    "_id": "$_projects",
                    "items": {"$topN": {"n": FILE_PREVIEW_LIMIT,
                        "sortBy": {"updated_at": -1, "id": 1},
                        "output": {"id": "$id", "name": "$name", "type": "$type", "size": "$size",
                                   "tags": {"algorithm": "$tags.algorithm"}, "updated_at": "$updated_at"}}},
                }}],
            }},
        ], allowDiskUse=True)
        file_rows = await file_cursor.to_list(length=1)
        file_result = file_rows[0] if file_rows else {"counts": [], "previews": []}
        for row in file_result["counts"]:
            file_stats_by_project[row["_id"]["project"]].append({"_id": {"type": row["_id"]["type"]}, "count": row["count"]})
        file_previews_by_project = {row["_id"]: row["items"] for row in file_result["previews"]}

    for project in selected:
        project_datasets: list[dict[str, Any]] = []
        dataset_counts = _asset_counts([])
        for dataset in datasets_by_project[project]:
            entry = {
                "id": dataset["id"], "name": dataset["name"],
                "current_version": dataset.get("current_version"),
                "updated_at": dataset.get("updated_at"),
                "counts": counts_by_dataset.get(dataset["id"], _asset_counts([])),
            }
            project_datasets.append(entry)
            for key, count in entry["counts"].items():
                dataset_counts[key] += count
        project_datasets.sort(key=lambda item: item["name"])

        models = []
        for model_id in model_project_sources[project]:
            asset = model_by_id[model_id]
            models.append({
                "id": model_id, "name": asset["name"], "remark": asset.get("remark") or "",
                "updated_at": asset.get("updated_at"),
                "sources": sorted(model_project_sources[project][model_id]),
                "versions": sorted(model_project_versions[project][model_id]),
                "configured_parameters": sorted(
                    [
                        {"id": metric_id, "name": metric_definitions[metric_id]["name"],
                         "category": metric_definitions[metric_id]["category"], "value": str(value)}
                        for metric_id, value in (asset.get("metric_values") or {}).items()
                        if metric_id in metric_definitions and value is not None and str(value).strip()
                    ],
                    key=lambda item: (item["category"], item["name"]),
                ),
                "latest_version_created_at": model_project_latest_version[project].get(model_id),
            })
        models.sort(key=lambda item: (-item["latest_version_created_at"] if item["latest_version_created_at"] is not None else float("inf"), item["name"], item["id"]))
        for item in models:
            item.pop("latest_version_created_at")

        file_counts = _asset_counts(file_stats_by_project[project])
        files = file_previews_by_project.get(project, [])
        file_total = sum(file_counts.values())

        result["projects"].append({
            "name": project,
            "dataset_count": len(project_datasets), "dataset_counts": dataset_counts,
            "datasets": project_datasets,
            "model_count": len(models), "models": models,
            "file_count": file_total, "file_counts": file_counts,
            "files": files, "files_truncated": file_total > len(files),
        })
    return result
