from typing import Any

from fastapi import APIRouter, Request

from ..audit import record_audit
from ..database import db
from ..dependencies import AssetEditUser, AssetReadUser
from ..errors import AppError
from ..schemas import ModelParameterUpdate
from ..utils import now

router = APIRouter(prefix="/assets/{asset_id}/parameters", tags=["model-parameters"])


async def model_asset(asset_id: str) -> dict[str, Any]:
    asset = await db.assets.find_one({"id": asset_id, "type": "model", "archived_at": None})
    if asset is None:
        raise AppError(404, "MODEL_ASSET_NOT_FOUND", "模型素材不存在或已归档")
    return asset


@router.get("")
async def get_model_parameters(asset_id: str, user: AssetReadUser) -> dict[str, Any]:
    asset = await model_asset(asset_id)
    categories = [item async for item in db.metric_categories.find().sort([("order", 1), ("created_at", 1)])]
    category_order = {item["name"]: index for index, item in enumerate(categories)}
    definitions = [item async for item in db.metric_definitions.find()]
    definitions.sort(key=lambda item: (category_order.get(item["category"], len(categories)), item["name"]))
    values = asset.get("metric_values") or {}
    return {
        "asset_id": asset_id,
        "items": [
            {
                "id": item["id"], "name": item["name"], "category": item["category"],
                "description": item.get("description", ""), "value": values.get(item["id"]),
            }
            for item in definitions
        ],
    }


@router.patch("")
async def update_model_parameters(
    asset_id: str, body: ModelParameterUpdate, request: Request, user: AssetEditUser,
) -> dict[str, Any]:
    await model_asset(asset_id)
    metric_ids = set(body.values)
    existing_ids = set(await db.metric_definitions.distinct("id", {"id": {"$in": list(metric_ids)}}))
    if metric_ids != existing_ids:
        raise AppError(400, "METRIC_DEFINITION_NOT_FOUND", "部分指标已被删除，请刷新后重试")
    values = {metric_id: value for metric_id, value in body.values.items() if value is not None}
    timestamp = now()
    result = await db.assets.update_one(
        {"id": asset_id, "type": "model", "archived_at": None},
        {"$set": {"metric_values": values, "modified_at": timestamp, "updated_at": timestamp}},
    )
    if not result.matched_count:
        raise AppError(404, "MODEL_ASSET_NOT_FOUND", "模型素材不存在或已归档")
    await record_audit(
        actor=user, action="asset.model_parameters_updated", object_type="asset",
        object_id=asset_id, object_name=None, request_id=request.state.request_id,
        changes={"configured_count": len(values)},
    )
    return await get_model_parameters(asset_id, user)
