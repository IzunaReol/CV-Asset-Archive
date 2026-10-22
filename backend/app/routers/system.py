import re
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Query
from pymongo import DESCENDING

from ..database import db
from ..dependencies import ReadUser
from ..permissions import effective_menu_permissions
from ..utils import now, public_document

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/overview")
async def system_overview(user: ReadUser) -> dict[str, Any]:
    menus = effective_menu_permissions(user)
    result: dict[str, Any] = {
        "counts": {}, "asset_types": {}, "asset_storage_by_type": {}, "recent_activity": []
    }
    if "library" in menus:
        active = {"archived_at": None}
        result["counts"]["assets"] = await db.assets.count_documents(active)
        result["counts"]["processing"] = await db.assets.count_documents({**active, "status": {"$in": ["queued", "processing"]}})
        aggregate_cursor = await db.assets.aggregate([
            {"$match": active},
            {"$group": {"_id": "$type", "count": {"$sum": 1}, "size": {"$sum": {"$ifNull": ["$size", 0]}}}},
        ])
        grouped = await aggregate_cursor.to_list(length=None)
        result["asset_types"] = {item["_id"]: item["count"] for item in grouped if item.get("_id")}
        result["asset_storage_by_type"] = {
            item["_id"]: {"count": item["count"], "size": item["size"]}
            for item in grouped if item.get("_id")
        }
    if "datasets" in menus:
        result["counts"]["datasets"] = await db.datasets.count_documents({"deleted_at": None})
    if "relations" in menus or "lineage" in menus:
        result["counts"]["relations"] = await db.relations.count_documents({"status": "active"})
    if "downloads" in menus:
        job_query = {} if {"admin", "data_manager"}.intersection(user.get("roles", [])) else {"owner_id": user["id"]}
        result["counts"]["running_jobs"] = await db.jobs.count_documents({**job_query, "state": {"$in": ["queued", "running"]}})
        result["counts"]["failed_jobs"] = await db.jobs.count_documents({
            **job_query, "state": "failed", "updated_at": {"$gte": now() - timedelta(days=7)},
        })
    if "logs" in menus:
        cursor = db.audit_logs.find({"action": {"$ne": "auth.session_invalid"}}).sort("created_at", DESCENDING).limit(8)
        result["recent_activity"] = [public_document(item) async for item in cursor]
    return result


@router.get("/search")
async def global_search(
    user: ReadUser,
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(6, ge=1, le=20),
) -> dict[str, Any]:
    menus = effective_menu_permissions(user)
    pattern = {"$regex": re.escape(q.strip()), "$options": "i"}
    groups: list[dict[str, Any]] = []
    if "library" in menus:
        asset_query = {"archived_at": None, "type": {"$ne": "model"}, "$or": [
            {"name": pattern}, {"original_filename": pattern}, {"remark": pattern}, {"project": pattern},
        ]}
        items = await db.assets.find(
            asset_query,
            {"_id": 0, "id": 1, "name": 1, "type": 1, "remark": 1},
        ).sort("updated_at", DESCENDING).limit(limit).to_list(length=None)
        groups.append({"type": "asset", "label": "素材", "total": await db.assets.count_documents(asset_query), "items": items})
        model_query = {"archived_at": None, "type": "model", "$or": [
            {"name": pattern}, {"original_filename": pattern}, {"remark": pattern}, {"project": pattern},
        ]}
        models = await db.assets.find(
            model_query,
            {"_id": 0, "id": 1, "name": 1, "type": 1, "remark": 1},
        ).sort("updated_at", DESCENDING).limit(limit).to_list(length=None)
        groups.append({"type": "model", "label": "模型", "total": await db.assets.count_documents(model_query), "items": models})
    if "datasets" in menus:
        dataset_query = {"deleted_at": None, "$or": [{"name": pattern}, {"remark": pattern}, {"description": pattern}]}
        items = await db.datasets.find(
            dataset_query,
            {"_id": 0, "id": 1, "name": 1, "status": 1, "remark": 1},
        ).sort("updated_at", DESCENDING).limit(limit).to_list(length=None)
        groups.append({"type": "dataset", "label": "数据集", "total": await db.datasets.count_documents(dataset_query), "items": items})
    if "downloads" in menus:
        job_query: dict[str, Any] = {} if {"admin", "data_manager"}.intersection(user.get("roles", [])) else {"owner_id": user["id"]}
        job_query["$or"] = [{"name": pattern}, {"type": pattern}]
        items = await db.jobs.find(
            job_query, {"_id": 0, "id": 1, "name": 1, "type": 1, "state": 1},
        ).sort("created_at", DESCENDING).limit(limit).to_list(length=None)
        groups.append({"type": "job", "label": "任务", "total": await db.jobs.count_documents(job_query), "items": items})
    if "relations" in menus or "lineage" in menus:
        matching_ids = set(await db.assets.distinct("id", {
            "archived_at": None, "$or": [{"name": pattern}, {"remark": pattern}],
        }))
        matching_ids.update(await db.dataset_versions.distinct("id", {
            "$or": [{"name": pattern}, {"version": pattern}, {"release_note": pattern}],
        }))
        relation_clauses: list[dict[str, Any]] = [
            {"relation_type": pattern}, {"remark": pattern}, {"created_by_name": pattern},
        ]
        if matching_ids:
            relation_clauses.extend([
                {"source_id": {"$in": list(matching_ids)}},
                {"target_id": {"$in": list(matching_ids)}},
            ])
        relation_query = {"$or": relation_clauses}
        relations = await db.relations.find(
            relation_query,
            {"_id": 0, "id": 1, "source_id": 1, "target_id": 1, "relation_type": 1, "status": 1, "remark": 1},
        ).sort("updated_at", DESCENDING).limit(limit).to_list(length=None)
        endpoint_ids = {value for item in relations for value in (item.get("source_id"), item.get("target_id")) if value}
        endpoint_names: dict[str, str] = {}
        if endpoint_ids:
            async for item in db.assets.find({"id": {"$in": list(endpoint_ids)}}, {"id": 1, "name": 1}):
                endpoint_names[item["id"]] = item.get("name", item["id"])
            async for item in db.dataset_versions.find({"id": {"$in": list(endpoint_ids)}}, {"id": 1, "name": 1, "version": 1}):
                endpoint_names[item["id"]] = item.get("name") or item.get("version") or item["id"]
        for item in relations:
            item["name"] = f'{endpoint_names.get(item.get("source_id"), "未知对象")} → {endpoint_names.get(item.get("target_id"), "未知对象")}'
        groups.append({"type": "relation", "label": "关联关系", "total": await db.relations.count_documents(relation_query), "items": relations})
    if "admin" in menus:
        user_query = {"$or": [{"username": pattern}, {"status": pattern}, {"roles": pattern}]}
        users = await db.users.find(
            user_query,
            {"_id": 0, "id": 1, "username": 1, "status": 1, "roles": 1},
        ).sort("updated_at", DESCENDING).limit(limit).to_list(length=None)
        for item in users:
            item["name"] = item.pop("username")
        groups.append({"type": "user", "label": "用户", "total": await db.users.count_documents(user_query), "items": users})
    if "roles" in menus or "admin" in menus:
        role_query = {"$or": [{"name": pattern}, {"description": pattern}]}
        roles = await db.role_templates.find(
            role_query,
            {"_id": 0, "id": 1, "name": 1, "description": 1},
        ).sort("updated_at", DESCENDING).limit(limit).to_list(length=None)
        fixed_names = {
            "admin": "管理员", "data_manager": "数据管理员", "annotator": "标注员",
            "ml_engineer": "算法工程师", "viewer": "只读访客",
        }
        overrides = {item["key"]: item async for item in db.role_overrides.find({})}
        search_text = q.strip().casefold()
        matching_fixed_count = 0
        for key, default_name in fixed_names.items():
            override = overrides.get(key, {})
            name = override.get("name", default_name)
            description = override.get("description", "")
            if not override.get("disabled") and search_text in f"{name} {description}".casefold():
                matching_fixed_count += 1
                roles.append({"id": f"fixed:{key}", "key": key, "name": name, "description": description})
        roles = roles[:limit]
        role_total = await db.role_templates.count_documents(role_query) + matching_fixed_count
        groups.append({"type": "role", "label": "角色", "total": role_total, "items": roles})
    if "logs" in menus:
        log_query = {"$or": [
            {"actor_username": pattern}, {"object_name": pattern}, {"object_type": pattern},
            {"action": pattern}, {"request_id": pattern}, {"client_ip": pattern},
        ]}
        logs = await db.audit_logs.find(
            log_query,
            {"_id": 0, "id": 1, "action": 1, "object_type": 1, "object_name": 1,
             "actor_username": 1, "request_id": 1, "created_at": 1, "changes": 1,
             "outcome": 1, "response_status": 1, "client_ip": 1},
        ).sort("created_at", DESCENDING).limit(limit).to_list(length=None)
        for item in logs:
            item["name"] = item.get("object_name") or item.get("action")
            item["remark"] = item.get("actor_username") or item.get("request_id")
        groups.append({"type": "log", "label": "系统日志", "total": await db.audit_logs.count_documents(log_query), "items": logs})
    return {"query": q.strip(), "groups": [group for group in groups if group["items"]]}
