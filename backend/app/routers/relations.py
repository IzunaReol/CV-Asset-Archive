import re
from datetime import datetime
from pathlib import PurePath
from typing import Any

from fastapi import APIRouter, Query, Request
from pymongo import DESCENDING

from ..audit import record_audit
from ..database import db
from ..dependencies import ManageUser, ReadUser, WriteUser
from ..errors import AppError
from ..schemas import (
    AnnotationMatchPreviewRequest,
    RelationBatchRequest,
    RelationCreate,
    RevokeRelationRequest,
)
from ..utils import new_id, now, public_document

router = APIRouter(prefix="/relations", tags=["relations"])


def relation_asset_summary(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": asset["id"],
        "name": asset.get("name", asset["id"]),
        "type": asset.get("type", asset.get("kind", "asset")),
        "tags": asset.get("tags", {}),
    }


def filename_stem(name: str) -> str:
    return PurePath(name).stem.casefold().strip()


def relation_type_error(
    source: dict[str, Any], target: dict[str, Any], relation_type: str
) -> tuple[str, str] | None:
    source_type = source.get("type", source.get("kind", "asset"))
    target_type = target.get("type", target.get("kind", "asset"))
    if relation_type == "annotates" and not (
        source_type == "annotation" and target_type == "image"
    ):
        return "RELATION_TYPE_MISMATCH", "对应标注关系必须由标注指向图片"
    if relation_type == "trained_on" and source_type != "model":
        return "RELATION_TYPE_MISMATCH", "训练关系的源对象必须是模型"
    if relation_type == "version_of" and source_type != target_type:
        return "RELATION_TYPE_MISMATCH", "版本关系的源对象和目标对象类型必须一致"
    return None


async def preview_relation_item(item: RelationCreate) -> dict[str, Any]:
    if item.source_id == item.target_id:
        return {
            "relation": item.model_dump(mode="json"),
            "code": "SELF_RELATION",
            "message": "不能关联素材自身",
        }
    source = await db.assets.find_one({"id": item.source_id, "archived_at": None})
    target = await db.assets.find_one({"id": item.target_id, "archived_at": None})
    target = (
        target
        or await db.dataset_versions.find_one({"id": item.target_id})
        or await db.datasets.find_one({"id": item.target_id, "deleted_at": None})
        or await db.collections.find_one({"id": item.target_id})
    )
    if source is None or target is None:
        return {
            "relation": item.model_dump(mode="json"),
            "code": "OBJECT_NOT_FOUND",
            "message": "源对象或目标对象不存在或已删除",
        }
    existing = await db.relations.find_one(
        {
            "source_id": item.source_id,
            "target_id": item.target_id,
            "relation_type": item.relation_type.value,
            "status": "active",
        }
    )
    result = {
        "relation": item.model_dump(mode="json"),
        "source": relation_asset_summary(source),
        "target": relation_asset_summary(target),
    }
    type_error = relation_type_error(source, target, item.relation_type.value)
    if type_error:
        code, message = type_error
        return {**result, "code": code, "message": message}
    if existing:
        return {
            **result,
            "code": "RELATION_EXISTS",
            "message": "关联关系已经存在",
            "existing_relation_id": existing["id"],
        }
    return {**result, "code": "READY", "message": "可以建立"}


async def validate_relation(body: RelationCreate) -> None:
    source = await db.assets.find_one({"id": body.source_id, "archived_at": None})
    target_asset = await db.assets.find_one({"id": body.target_id, "archived_at": None})
    target_collection = (
        await db.dataset_versions.find_one({"id": body.target_id})
        or await db.datasets.find_one({"id": body.target_id, "deleted_at": None})
        or await db.collections.find_one({"id": body.target_id})
    )
    if source is None or (target_asset is None and target_collection is None):
        raise AppError(404, "RELATION_TARGET_NOT_FOUND", "源资产或目标对象不存在")
    type_error = relation_type_error(
        source, target_asset or target_collection or {}, body.relation_type.value
    )
    if type_error:
        code, message = type_error
        raise AppError(422, code, message)


@router.post("", status_code=201)
async def create_relation(
    body: RelationCreate, request: Request, user: WriteUser
) -> dict[str, Any]:
    await validate_relation(body)
    previous = await db.relations.find_one(
        {
            "source_id": body.source_id,
            "target_id": body.target_id,
            "relation_type": body.relation_type.value,
        },
        sort=[("revision", DESCENDING)],
    )
    if previous and previous["status"] == "active":
        raise AppError(409, "RELATION_EXISTS", "该关联关系已经存在")
    relation = {
        "id": new_id(),
        "source_id": body.source_id,
        "target_id": body.target_id,
        "relation_type": body.relation_type.value,
        "provenance": body.provenance,
        "revision": (previous or {}).get("revision", 0) + 1,
        "status": "active",
        "created_by": user["id"],
        "created_by_name": user["username"],
        "created_at": now(),
    }
    await db.relations.insert_one(relation)
    await record_audit(
        actor=user,
        action="relation.created",
        object_type="relation",
        object_id=relation["id"],
        request_id=request.state.request_id,
    )
    return public_document(relation) or {}


@router.post("/batch")
async def create_relations(
    body: RelationBatchRequest, request: Request, user: WriteUser
) -> dict[str, Any]:
    succeeded, failed = [], []
    for item in body.relations:
        try:
            relation = await create_relation(item, request, user)
            succeeded.append(relation)
        except AppError as exc:
            failed.append(
                {
                    "source_id": item.source_id,
                    "target_id": item.target_id,
                    "code": exc.code,
                    "message": exc.message,
                }
            )
    return {"succeeded": succeeded, "failed": failed}


@router.post("/preview")
async def preview_relations(body: RelationBatchRequest, user: ReadUser) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {"ready": [], "existing": [], "invalid": []}
    for item in body.relations:
        result = await preview_relation_item(item)
        if result["code"] == "READY":
            groups["ready"].append(result)
        elif result["code"] == "RELATION_EXISTS":
            groups["existing"].append(result)
        else:
            groups["invalid"].append(result)
    return {**groups, "counts": {key: len(value) for key, value in groups.items()}}


@router.post("/annotation-match-preview")
async def preview_annotation_matches(
    body: AnnotationMatchPreviewRequest, user: ReadUser
) -> dict[str, Any]:
    requested_image_ids = list(dict.fromkeys(body.image_ids))
    requested_annotation_ids = list(dict.fromkeys(body.annotation_ids))
    scan_all = not requested_image_ids and not requested_annotation_ids
    requested_ids = [*requested_image_ids, *requested_annotation_ids]
    assets: dict[str, dict[str, Any]] = {}
    if requested_ids:
        assets = {
            item["id"]: item
            async for item in db.assets.find(
                {"id": {"$in": requested_ids}, "archived_at": None},
                {"id": 1, "name": 1, "type": 1, "tags": 1, "media": 1},
            )
        }

    invalid = []
    for asset_id, expected_type, message in [
        *[(item, "image", "图片不存在、已删除或类型不正确") for item in requested_image_ids],
        *[
            (item, "annotation", "标注不存在、已删除或类型不正确")
            for item in requested_annotation_ids
        ],
    ]:
        asset = assets.get(asset_id)
        if asset is None or asset.get("type") != expected_type:
            invalid.append({"id": asset_id, "expected_type": expected_type, "message": message})

    all_assets = [
        item
        async for item in db.assets.find(
            {"type": {"$in": ["image", "annotation"]}, "archived_at": None},
            {"id": 1, "name": 1, "type": 1, "tags": 1, "media": 1},
        )
    ]
    selected_images = (
        [item for item in all_assets if item["type"] == "image"]
        if scan_all
        else [
            assets[item]
            for item in requested_image_ids
            if assets.get(item, {}).get("type") == "image"
        ]
    )
    selected_annotations = (
        [item for item in all_assets if item["type"] == "annotation"]
        if scan_all
        else [
            assets[item]
            for item in requested_annotation_ids
            if assets.get(item, {}).get("type") == "annotation"
        ]
    )

    images_by_stem: dict[str, list[dict[str, Any]]] = {}
    for image in all_assets:
        if image["type"] == "image":
            images_by_stem.setdefault(filename_stem(image["name"]), []).append(image)

    claims_by_stem: dict[str, list[dict[str, Any]]] = {}
    annotation_claims: dict[str, set[str]] = {}
    for annotation in all_assets:
        if annotation["type"] != "annotation":
            continue
        references = annotation.get("media", {}).get("image_refs") or [annotation["name"]]
        stems = {filename_stem(str(reference)) for reference in references if reference}
        annotation_claims[annotation["id"]] = stems
        for stem in stems:
            claims_by_stem.setdefault(stem, []).append(annotation)

    selected_image_ids = {item["id"] for item in selected_images}
    selected_annotation_ids = {item["id"] for item in selected_annotations}
    candidate_stems = {
        stem for image in selected_images for stem in [filename_stem(image["name"])]
    } | {
        stem
        for annotation in selected_annotations
        for stem in annotation_claims.get(annotation["id"], set())
    }

    relation_query: dict[str, Any] = {
        "relation_type": "annotates",
        "status": "active",
    }
    active_relations = [item async for item in db.relations.find(relation_query)]
    existing_pairs = {(item["source_id"], item["target_id"]): item for item in active_relations}
    images_with_relation = {item["target_id"] for item in active_relations}
    ready = []
    existing = []
    image_conflicts = []
    annotation_conflicts = []
    conflicted_annotation_ids: set[str] = set()
    unmatched_images = []
    matched_annotation_ids: set[str] = set()

    for stem in sorted(candidate_stems):
        images = images_by_stem.get(stem, [])
        annotations = claims_by_stem.get(stem, [])
        if not scan_all:
            images = [item for item in images if item["id"] in selected_image_ids]
            annotations = [item for item in annotations if item["id"] in selected_annotation_ids]
        if len(images) > 1:
            image_conflicts.append(
                {"stem": stem, "items": [relation_asset_summary(item) for item in images]}
            )
            continue
        if len(annotations) > 1:
            conflicted_annotation_ids.update(item["id"] for item in annotations)
            annotation_conflicts.append(
                {
                    "stem": stem,
                    "items": [relation_asset_summary(item) for item in annotations],
                }
            )
            continue
        if not images:
            continue
        image = images[0]
        if not annotations:
            unmatched_images.append(relation_asset_summary(image))
            continue
        annotation = annotations[0]
        matched_annotation_ids.add(annotation["id"])
        pair = {
            "source": relation_asset_summary(annotation),
            "target": relation_asset_summary(image),
            "relation_type": "annotates",
        }
        previous = existing_pairs.get((annotation["id"], image["id"]))
        if previous or image["id"] in images_with_relation:
            existing.append({**pair, "existing_relation_id": (previous or {}).get("id")})
        else:
            ready.append(pair)

    unmatched_annotations = [
        relation_asset_summary(item)
        for item in selected_annotations
        if item["id"] not in matched_annotation_ids and item["id"] not in conflicted_annotation_ids
    ]
    return {
        "ready": ready,
        "existing": existing,
        "image_conflicts": image_conflicts,
        "annotation_conflicts": annotation_conflicts,
        "unmatched_images": unmatched_images,
        "unmatched_annotations": unmatched_annotations,
        "invalid": invalid,
        "counts": {
            "ready": len(ready),
            "existing": len(existing),
            "image_conflicts": len(image_conflicts),
            "annotation_conflicts": len(annotation_conflicts),
            "unmatched_images": len(unmatched_images),
            "unmatched_annotations": len(unmatched_annotations),
            "invalid": len(invalid),
        },
    }


@router.get("")
async def list_relations(
    user: ReadUser,
    q: str = "",
    relation_type: str | None = None,
    created_by: str = "",
    status: str | None = Query(None, pattern="^(active|revoked)$"),
    created_from: str | None = None,
    created_to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = []
    if status:
        clauses.append({"status": status})
    if relation_type:
        clauses.append({"relation_type": relation_type})
    if created_by.strip():
        clauses.append(
            {"created_by_name": {"$regex": re.escape(created_by.strip()), "$options": "i"}}
        )
    if created_from or created_to:
        date_condition: dict[str, Any] = {}
        try:
            if created_from:
                date_condition["$gte"] = datetime.fromisoformat(created_from)
            if created_to:
                date_condition["$lte"] = datetime.fromisoformat(created_to)
        except ValueError as exc:
            raise AppError(400, "INVALID_DATE_FILTER", "关系创建时间格式不正确") from exc
        clauses.append({"created_at": date_condition})
    if q.strip():
        keyword = re.escape(q.strip())
        matching_asset_ids = await db.assets.distinct(
            "id",
            {
                "$or": [
                    {"name": {"$regex": keyword, "$options": "i"}},
                    {"remark": {"$regex": keyword, "$options": "i"}},
                ]
            },
        )
        matching_collection_ids = await db.collections.distinct(
            "id", {"name": {"$regex": keyword, "$options": "i"}}
        )
        clauses.append(
            {
                "$or": [
                    {"source_id": {"$in": matching_asset_ids}},
                    {"target_id": {"$in": [*matching_asset_ids, *matching_collection_ids]}},
                ]
            }
        )
    query = {"$and": clauses} if clauses else {}
    total = await db.relations.count_documents(query)
    cursor = (
        db.relations.find(query)
        .sort("created_at", DESCENDING)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = []
    async for relation in cursor:
        source = await db.assets.find_one(
            {"id": relation["source_id"]}, {"id": 1, "name": 1, "type": 1, "tags": 1}
        )
        target = await db.assets.find_one(
            {"id": relation["target_id"]}, {"id": 1, "name": 1, "type": 1, "tags": 1}
        ) or await db.collections.find_one(
            {"id": relation["target_id"]}, {"id": 1, "name": 1, "kind": 1}
        )
        item = public_document(relation) or {}
        item.update(
            {
                "source_name": (source or {}).get("name", relation["source_id"]),
                "source_type": (source or {}).get("type", "asset"),
                "target_name": (target or {}).get("name", relation["target_id"]),
                "target_type": (target or {}).get("type", (target or {}).get("kind", "asset")),
                "source_summary": relation_asset_summary(source) if source else None,
                "target_summary": relation_asset_summary(target) if target else None,
            }
        )
        items.append(item)
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/{relation_id}")
async def get_relation(relation_id: str, user: ReadUser) -> dict[str, Any]:
    relation = await db.relations.find_one({"id": relation_id})
    if relation is None:
        raise AppError(404, "RELATION_NOT_FOUND", "关联关系不存在")
    source = await db.assets.find_one({"id": relation["source_id"]})
    target = (
        await db.assets.find_one({"id": relation["target_id"]})
        or await db.dataset_versions.find_one({"id": relation["target_id"]})
        or await db.datasets.find_one({"id": relation["target_id"]})
        or await db.collections.find_one({"id": relation["target_id"]})
    )
    return {
        **(public_document(relation) or {}),
        "source": public_document(source),
        "target": public_document(target),
    }


@router.post("/{relation_id}/revoke")
async def revoke_relation(
    relation_id: str, body: RevokeRelationRequest, request: Request, user: ManageUser
) -> dict[str, Any]:
    relation = await db.relations.find_one({"id": relation_id})
    if relation is None:
        raise AppError(404, "RELATION_NOT_FOUND", "关联关系不存在")
    if relation["status"] == "revoked":
        return public_document(relation) or {}
    collection = await db.collections.find_one(
        {"id": relation["target_id"], "frozen_at": {"$ne": None}}
    )
    if collection and relation["relation_type"] == "contains":
        raise AppError(409, "RELATION_IMMUTABLE", "冻结数据集成员关系不可撤销，请创建新版本")
    changes = {
        "status": "revoked",
        "revoked_at": now(),
        "revoked_by": user["id"],
        "revoke_reason": body.reason,
        "replacement_relation_id": body.replacement_relation_id,
    }
    await db.relations.update_one({"id": relation_id, "status": "active"}, {"$set": changes})
    await record_audit(
        actor=user,
        action="relation.revoked",
        object_type="relation",
        object_id=relation_id,
        request_id=request.state.request_id,
        changes={"reason": body.reason},
    )
    return public_document(await db.relations.find_one({"id": relation_id})) or {}


@router.get("/graph/{asset_id}")
async def relation_graph(
    asset_id: str, user: ReadUser, depth: int = Query(2, ge=1, le=4)
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    frontier = {asset_id}
    visited: set[str] = set()
    for _ in range(depth):
        if not frontier:
            break
        cursor = db.relations.find(
            {
                "status": "active",
                "$or": [
                    {"source_id": {"$in": list(frontier)}},
                    {"target_id": {"$in": list(frontier)}},
                ],
            }
        )
        next_frontier: set[str] = set()
        async for relation in cursor:
            edge = public_document(relation) or {}
            source = (
                await db.assets.find_one({"id": relation["source_id"]})
                or await db.dataset_versions.find_one({"id": relation["source_id"]})
                or await db.datasets.find_one({"id": relation["source_id"]})
                or await db.collections.find_one({"id": relation["source_id"]})
            )
            target = (
                await db.assets.find_one({"id": relation["target_id"]})
                or await db.dataset_versions.find_one({"id": relation["target_id"]})
                or await db.datasets.find_one({"id": relation["target_id"]})
                or await db.collections.find_one({"id": relation["target_id"]})
            )
            edge.update(
                {
                    "source_name": (source or {}).get("name", relation["source_id"]),
                    "source_type": (source or {}).get("type", (source or {}).get("kind", "asset")),
                    "target_name": (target or {}).get("name", relation["target_id"]),
                    "target_type": (target or {}).get("type", (target or {}).get("kind", "asset")),
                }
            )
            edges[relation["id"]] = edge
            next_frontier.update([relation["source_id"], relation["target_id"]])
        visited.update(frontier)
        frontier = next_frontier - visited
    ids = list(visited | frontier)
    async for asset in db.assets.find({"id": {"$in": ids}}):
        nodes[asset["id"]] = public_document(asset) or {}
    async for collection in db.collections.find({"id": {"$in": ids}}):
        nodes[collection["id"]] = public_document(collection) or {}
    async for dataset in db.datasets.find({"id": {"$in": ids}}):
        nodes[dataset["id"]] = public_document(dataset) or {}
    version_rows = await db.dataset_versions.find({"id": {"$in": ids}}).to_list(length=len(ids))
    version_ids = [item["id"] for item in version_rows]
    version_counts: dict[str, dict[str, int]] = {}
    if version_ids:
        pipeline = [
            {"$match": {"version_id": {"$in": version_ids}}},
            {"$group": {"_id": {"version_id": "$version_id", "type": "$snapshot.type"}, "count": {"$sum": 1}}},
        ]
        version_count_cursor = await db.dataset_version_memberships.aggregate(pipeline)
        async for row in version_count_cursor:
            version_counts.setdefault(row["_id"]["version_id"], {})[row["_id"]["type"]] = row["count"]
    dataset_ids = list({item.get("dataset_id") for item in version_rows if item.get("dataset_id")})
    dataset_names = {
        item["id"]: item.get("name", item["id"])
        async for item in db.datasets.find({"id": {"$in": dataset_ids}}, {"id": 1, "name": 1})
    }
    for version in version_rows:
        node = public_document(version) or {}
        node["dataset_name"] = dataset_names.get(version.get("dataset_id"), version.get("name", "数据集"))
        node["counts"] = version_counts.get(version["id"], {})
        nodes[version["id"]] = node
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}
