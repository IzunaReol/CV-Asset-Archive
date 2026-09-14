from datetime import UTC, datetime

import pytest
from backend.app.errors import AppError
from backend.app.routers.assets import asset_filter_clause, updated_asset_tags


def test_add_same_tag_type_keeps_existing_values() -> None:
    result = updated_asset_tags(
        {"status": "已标注"},
        {"status": "已训练"},
        [],
        {},
    )

    assert result["status"] == ["已标注", "已训练"]


def test_remove_one_tag_value_keeps_other_values() -> None:
    result = updated_asset_tags(
        {"status": ["已标注", "已训练"], "scene": "室内"},
        {},
        [],
        {"status": ["已标注"]},
    )

    assert result == {"status": ["已训练"], "scene": "室内"}


def test_datetime_filter_builds_bounded_range() -> None:
    clause = asset_filter_clause(
        "created_at",
        "between",
        "2026-09-12T00:00:00Z|2026-09-12T00:02:00Z",
    )

    assert clause == {
        "created_at": {
            "$gte": datetime(2026, 9, 12, tzinfo=UTC),
            "$lte": datetime(2026, 9, 12, 0, 2, tzinfo=UTC),
        }
    }


def test_datetime_filter_rejects_reversed_range() -> None:
    with pytest.raises(AppError):
        asset_filter_clause(
            "updated_at",
            "between",
            "2026-09-12T00:02:00Z|2026-09-12T00:00:00Z",
        )
