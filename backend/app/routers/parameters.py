from typing import Any

from fastapi import APIRouter, Request
from pymongo.errors import DuplicateKeyError

from ..audit import record_audit
from ..database import db
from ..dependencies import ParameterManageUser, ParameterReadUser
from ..errors import AppError
from ..schemas import MetricCategoryCreate, MetricDefinitionWrite
from ..utils import new_id, now, public_document

router = APIRouter(prefix="/metric-definitions", tags=["metric-definitions"])
category_router = APIRouter(prefix="/metric-categories", tags=["metric-categories"])


@category_router.get("")
async def list_categories(user: ParameterReadUser) -> dict[str, Any]:
    return {
        "items": [
            public_document(item)
            async for item in db.metric_categories.find().sort([("order", 1), ("created_at", 1)])
        ]
    }


@category_router.post("", status_code=201)
async def create_category(
    body: MetricCategoryCreate, request: Request, user: ParameterManageUser
) -> dict[str, Any]:
    document = {
        "id": new_id(), "name": body.name, "order": 100,
        "built_in": False, "created_by": user["id"],
        "created_at": now(), "updated_at": now(),
    }
    try:
        await db.metric_categories.insert_one(document)
    except DuplicateKeyError as exc:
        raise AppError(409, "METRIC_CATEGORY_EXISTS", "指标分类已存在") from exc
    await record_audit(
        actor=user, action="metric_category.created", object_type="metric_category",
        object_id=document["id"], object_name=body.name,
        request_id=request.state.request_id,
    )
    return public_document(document) or {}


@category_router.delete("/{category_id}", status_code=204)
async def delete_category(
    category_id: str, request: Request, user: ParameterManageUser
) -> None:
    current = await db.metric_categories.find_one({"id": category_id})
    if current is None:
        raise AppError(404, "METRIC_CATEGORY_NOT_FOUND", "指标分类不存在")
    if current.get("built_in"):
        raise AppError(409, "BUILT_IN_CATEGORY_PROTECTED", "预置分类不允许删除")
    if await db.metric_definitions.count_documents({"category": current["name"]}, limit=1):
        raise AppError(409, "METRIC_CATEGORY_IN_USE", "分类下仍有指标，请先删除或移走指标")
    result = await db.metric_categories.delete_one({"id": category_id, "built_in": False})
    if not result.deleted_count:
        raise AppError(404, "METRIC_CATEGORY_NOT_FOUND", "指标分类不存在")
    await record_audit(
        actor=user, action="metric_category.deleted", object_type="metric_category",
        object_id=category_id, object_name=current["name"],
        request_id=request.state.request_id,
    )


@category_router.patch("/{category_id}")
async def update_category(
    category_id: str, body: MetricCategoryCreate, request: Request,
    user: ParameterManageUser,
) -> dict[str, Any]:
    current = await db.metric_categories.find_one({"id": category_id})
    if current is None:
        raise AppError(404, "METRIC_CATEGORY_NOT_FOUND", "指标分类不存在")
    if current.get("built_in"):
        raise AppError(409, "BUILT_IN_CATEGORY_PROTECTED", "预置分类不允许修改")
    if body.name == current["name"]:
        return public_document(current) or {}
    try:
        result = await db.metric_categories.update_one(
            {"id": category_id, "built_in": False},
            {"$set": {"name": body.name, "updated_at": now()}},
        )
    except DuplicateKeyError as exc:
        raise AppError(409, "METRIC_CATEGORY_EXISTS", "指标分类已存在") from exc
    if not result.matched_count:
        raise AppError(404, "METRIC_CATEGORY_NOT_FOUND", "指标分类不存在")
    await db.metric_definitions.update_many(
        {"category": current["name"]},
        {"$set": {"category": body.name, "updated_at": now()}},
    )
    await record_audit(
        actor=user, action="metric_category.updated", object_type="metric_category",
        object_id=category_id, object_name=body.name,
        request_id=request.state.request_id,
        changes={"name": {"before": current["name"], "after": body.name}},
    )
    return public_document(await db.metric_categories.find_one({"id": category_id})) or {}


async def ensure_category_exists(name: str) -> None:
    if await db.metric_categories.find_one({"name": name}) is None:
        raise AppError(400, "METRIC_CATEGORY_NOT_FOUND", "指标分类不存在，请先新增分类")


@router.get("")
async def list_metrics(user: ParameterReadUser) -> dict[str, Any]:
    return {
        "items": [
            public_document(item)
            async for item in db.metric_definitions.find().sort([("category", 1), ("name", 1)])
        ]
    }


@router.post("", status_code=201)
async def create_metric(
    body: MetricDefinitionWrite, request: Request, user: ParameterManageUser
) -> dict[str, Any]:
    await ensure_category_exists(body.category)
    document = {
        "id": new_id(), **body.model_dump(), "built_in": False,
        "created_by": user["id"], "created_at": now(), "updated_at": now(),
    }
    try:
        await db.metric_definitions.insert_one(document)
    except DuplicateKeyError as exc:
        raise AppError(409, "METRIC_DEFINITION_EXISTS", "该分类下指标名称已存在") from exc
    await record_audit(
        actor=user, action="metric_definition.created", object_type="metric_definition",
        object_id=document["id"], object_name=body.name,
        request_id=request.state.request_id,
    )
    return public_document(document) or {}


@router.patch("/{metric_id}")
async def update_metric(
    metric_id: str, body: MetricDefinitionWrite, request: Request,
    user: ParameterManageUser,
) -> dict[str, Any]:
    await ensure_category_exists(body.category)
    try:
        result = await db.metric_definitions.update_one(
            {"id": metric_id}, {"$set": {**body.model_dump(), "updated_at": now()}}
        )
    except DuplicateKeyError as exc:
        raise AppError(409, "METRIC_DEFINITION_EXISTS", "该分类下指标名称已存在") from exc
    if not result.matched_count:
        raise AppError(404, "METRIC_DEFINITION_NOT_FOUND", "指标参数不存在")
    await record_audit(
        actor=user, action="metric_definition.updated", object_type="metric_definition",
        object_id=metric_id, object_name=body.name,
        request_id=request.state.request_id,
        changes=body.model_dump(),
    )
    return public_document(await db.metric_definitions.find_one({"id": metric_id})) or {}


@router.delete("/{metric_id}", status_code=204)
async def delete_metric(
    metric_id: str, request: Request, user: ParameterManageUser
) -> None:
    current = await db.metric_definitions.find_one({"id": metric_id})
    if current is None:
        raise AppError(404, "METRIC_DEFINITION_NOT_FOUND", "指标参数不存在")
    if current.get("built_in"):
        raise AppError(409, "BUILT_IN_METRIC_PROTECTED", "预置指标不允许删除")
    await db.metric_definitions.delete_one({"id": metric_id, "built_in": False})
    await db.assets.update_many(
        {"type": "model", f"metric_values.{metric_id}": {"$exists": True}},
        {"$unset": {f"metric_values.{metric_id}": ""}},
    )
    await record_audit(
        actor=user, action="metric_definition.deleted", object_type="metric_definition",
        object_id=metric_id, object_name=current["name"],
        request_id=request.state.request_id,
    )
