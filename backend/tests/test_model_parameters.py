from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.errors import AppError
from app.routers import model_parameters
from app.schemas import ModelParameterUpdate


class Cursor:
    def __init__(self, items):
        self.items = items

    def sort(self, *args):
        return self

    def __aiter__(self):
        self.iterator = iter(self.items)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration:
            raise StopAsyncIteration


@pytest.mark.asyncio
async def test_model_parameters_show_unconfigured_and_save_per_model(monkeypatch):
    model = {"id": "model-1", "type": "model", "name": "模型一", "metric_values": {"accuracy": "0.95"}}
    assets = SimpleNamespace(
        find_one=AsyncMock(return_value=model),
        update_one=AsyncMock(return_value=SimpleNamespace(matched_count=1)),
    )
    definitions = SimpleNamespace(
        find=lambda: Cursor([
            {"id": "accuracy", "name": "准确率", "category": "图像分类", "description": "说明"},
            {"id": "map", "name": "mAP", "category": "目标检测", "description": "说明"},
        ]),
        distinct=AsyncMock(return_value=["accuracy", "map"]),
    )
    categories = SimpleNamespace(find=lambda: Cursor([
        {"name": "图像分类"}, {"name": "目标检测"},
    ]))
    monkeypatch.setattr(model_parameters, "db", SimpleNamespace(
        assets=assets, metric_definitions=definitions, metric_categories=categories,
    ))
    monkeypatch.setattr(model_parameters, "record_audit", AsyncMock())
    user = {"id": "user-1", "username": "admin"}
    before = await model_parameters.get_model_parameters("model-1", user)
    assert [(item["id"], item["value"]) for item in before["items"]] == [
        ("accuracy", "0.95"), ("map", None),
    ]

    await model_parameters.update_model_parameters(
        "model-1", ModelParameterUpdate(values={"accuracy": " 0.97 ", "map": " "}),
        SimpleNamespace(state=SimpleNamespace(request_id="request-1")), user,
    )
    assert assets.update_one.call_args.args[1]["$set"]["metric_values"] == {"accuracy": "0.97"}
    assert assets.update_one.call_args.args[0]["id"] == "model-1"
    changes = assets.update_one.call_args.args[1]["$set"]
    assert changes["modified_at"] == changes["updated_at"]


@pytest.mark.asyncio
async def test_model_parameters_reject_non_model_and_removed_definition(monkeypatch):
    assets = SimpleNamespace(find_one=AsyncMock(return_value=None), update_one=AsyncMock())
    definitions = SimpleNamespace(distinct=AsyncMock(return_value=[]))
    monkeypatch.setattr(model_parameters, "db", SimpleNamespace(assets=assets, metric_definitions=definitions))
    with pytest.raises(AppError) as missing:
        await model_parameters.get_model_parameters("image-1", {"id": "user-1"})
    assert missing.value.code == "MODEL_ASSET_NOT_FOUND"

    assets.find_one.return_value = {"id": "model-1", "type": "model"}
    with pytest.raises(AppError) as deleted:
        await model_parameters.update_model_parameters(
            "model-1", ModelParameterUpdate(values={"deleted-metric": "0.5"}),
            SimpleNamespace(state=SimpleNamespace(request_id="request-1")), {"id": "user-1"},
        )
    assert deleted.value.code == "METRIC_DEFINITION_NOT_FOUND"
    assets.update_one.assert_not_awaited()


def test_model_parameter_value_validation():
    assert ModelParameterUpdate(values={"metric-1": " "}).values == {"metric-1": None}
    with pytest.raises(ValidationError):
        ModelParameterUpdate(values={"metric-1": "x" * 201})
