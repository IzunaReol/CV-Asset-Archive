from datetime import UTC, datetime

import pytest
from app.errors import AppError
from app.routers.assets import (
    asset_filter_clause,
    chunk_prefix,
    parse_filter_datetime,
    safe_filename,
    updated_asset_tags,
)


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


def test_filter_datetime_normalizes_naive_value_to_utc() -> None:
    assert parse_filter_datetime("2026-09-12T08:30:00") == datetime(
        2026, 9, 12, 8, 30, tzinfo=UTC
    )


def test_filter_datetime_rejects_invalid_value() -> None:
    with pytest.raises(AppError) as exc_info:
        parse_filter_datetime("not-a-date")
    assert exc_info.value.code == "INVALID_DATE_FILTER"


def test_updated_at_filter_falls_back_to_created_at() -> None:
    clause = asset_filter_clause("updated_at", "gt", "2026-09-12T00:00:00Z")
    moment = datetime(2026, 9, 12, tzinfo=UTC)
    assert clause == {
        "$or": [
            {"modified_at": {"$gt": moment}},
            {"modified_at": {"$exists": False}, "created_at": {"$gt": moment}},
        ]
    }


@pytest.mark.parametrize(
    ("operator", "expected"),
    [
        ("equals", {"tags.scene": "室内"}),
        ("notEquals", {"tags.scene": {"$ne": "室内"}}),
        ("contains", {"tags.scene": {"$regex": "室内", "$options": "i"}}),
        (
            "notContains",
            {"tags.scene": {"$not": {"$regex": "室内", "$options": "i"}}},
        ),
    ],
)
def test_tag_filter_operators(operator: str, expected: dict) -> None:
    assert asset_filter_clause("scene", operator, "室内") == expected


def test_tag_filter_escapes_regex_characters() -> None:
    assert asset_filter_clause("remark", "contains", "a.b")["remark"]["$regex"] == "a\\.b"


def test_invalid_filter_operator_is_rejected() -> None:
    with pytest.raises(AppError) as exc_info:
        asset_filter_clause("remark", "notEquals", "草稿")
    assert exc_info.value.code == "INVALID_TAG_OPERATOR"


def test_removing_last_tag_value_and_key_cleans_up_tags() -> None:
    result = updated_asset_tags(
        {"status": "已标注", "scene": ["室内"], "owner": "用户A"},
        {"status": ["已标注", "已训练", "已训练", ""]},
        ["owner"],
        {"scene": ["室内"]},
    )
    assert result == {"status": ["已标注", "已训练"]}


def test_upload_paths_do_not_keep_client_directories() -> None:
    assert safe_filename(r"..\临时目录\sample?.jpg") == "sample_.jpg"
    assert chunk_prefix("session-1") == "uploads/session-1/"
