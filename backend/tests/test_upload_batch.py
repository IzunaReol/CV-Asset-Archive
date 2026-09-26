import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.errors import AppError
from app.routers import assets
from app.schemas import UploadBatchCompleteRequest, UploadBatchInitRequest
from app.schemas import ExportCreate


def test_batch_upload_returns_per_file_results(monkeypatch):
    async def initialize(item, user):
        if item.filename == "bad.jpg":
            raise AppError(413, "FILE_TOO_LARGE", "文件过大")
        return {"upload_session_id": item.filename}

    monkeypatch.setattr(assets, "initialize_upload", initialize)
    body = UploadBatchInitRequest(files=[
        {"filename": "one.jpg", "size": 1, "mime_type": "image/jpeg", "asset_type": "image"},
        {"filename": "bad.jpg", "size": 2, "mime_type": "image/jpeg", "asset_type": "image"},
        {"filename": "two.jpg", "size": 3, "mime_type": "image/jpeg", "asset_type": "image"},
    ])
    result = asyncio.run(assets.initialize_upload_batch(body, {"id": "user"}))
    assert [item["index"] for item in result["items"]] == [0, 1, 2]
    assert result["items"][0]["session"]["upload_session_id"] == "one.jpg"
    assert result["items"][1]["error"]["code"] == "FILE_TOO_LARGE"
    assert result["items"][2]["session"]["upload_session_id"] == "two.jpg"


def test_batch_completion_keeps_successes_when_one_session_fails(monkeypatch):
    async def complete(item, request, user):
        if item.upload_session_id == "bad":
            raise AppError(409, "UPLOAD_INCOMPLETE", "未上传完成")
        return {"id": item.upload_session_id}

    monkeypatch.setattr(assets, "complete_upload", complete)
    request = SimpleNamespace(state=SimpleNamespace(request_id="test"))
    body = UploadBatchCompleteRequest(upload_session_ids=["good", "bad"], tags={"status": ["新"]})
    result = asyncio.run(assets.complete_upload_batch(body, request, {"id": "user"}))
    assert result["items"] == [
        {"index": 0, "asset": {"id": "good"}},
        {"index": 1, "error": {"code": "UPLOAD_INCOMPLETE", "message": "未上传完成"}},
    ]


def test_export_request_rejects_raw_database_query():
    try:
        ExportCreate.model_validate({"name": "bad", "query": {"$where": "true"}})
    except Exception as exc:
        assert "extra_forbidden" in str(exc)
    else:
        raise AssertionError("raw query must be rejected")


def test_large_upload_uses_chunks(monkeypatch):
    inserted = {}

    class UploadSessions:
        async def insert_one(self, document):
            inserted.update(document)

    class Assets:
        async def find_one(self, *args, **kwargs):
            return None

        def find(self, *args, **kwargs):
            return SimpleNamespace(
                sort=lambda *args, **kwargs: SimpleNamespace(
                    to_list=AsyncMock(return_value=[])
                )
            )

    monkeypatch.setattr(assets, "db", SimpleNamespace(
        assets=Assets(), upload_sessions=UploadSessions()
    ))
    result = asyncio.run(assets.initialize_upload(
        assets.UploadInitRequest(
            filename="large.bin", size=assets.CHUNK_THRESHOLD,
            mime_type="application/octet-stream", asset_type="other",
        ),
        {"id": "user"},
    ))
    assert result["transfer_mode"] == "chunks"
    assert result["chunk_count"] == 1
    assert result["upload_url"] is None
    assert inserted["transfer_mode"] == "chunks"


def test_upload_conflicts_are_grouped_by_asset_type(monkeypatch):
    async def matches(filename, asset_type):
        if filename.casefold() == "same.jpg" and asset_type == "image":
            return [{"id": "old-image", "name": "same.jpg", "type": "image"}]
        if filename.casefold() == "labels.xml" and asset_type == "annotation":
            return [{"id": "old-label", "name": "labels.xml", "type": "annotation"}]
        return []

    monkeypatch.setattr(assets, "matching_name_assets", matches)
    monkeypatch.setattr(
        assets,
        "db",
        SimpleNamespace(
            relations=SimpleNamespace(
                distinct=AsyncMock(side_effect=[["old-image"], [], [], ["old-label"]])
            )
        ),
    )
    body = assets.UploadConflictCheckRequest(files=[
        {"filename": "SAME.jpg", "size": 10, "mime_type": "image/jpeg", "asset_type": "image"},
        {"filename": "labels.xml", "size": 20, "mime_type": "application/xml", "asset_type": "annotation"},
        {"filename": "new.mp4", "size": 30, "mime_type": "video/mp4", "asset_type": "video"},
    ])

    result = asyncio.run(assets.check_upload_conflicts(body, {"id": "user"}))

    assert result["total"] == 2
    assert [(group["asset_type"], group["count"]) for group in result["groups"]] == [
        ("image", 1),
        ("annotation", 1),
    ]
    assert result["groups"][0]["items"][0]["has_active_relations"] is True
    assert result["groups"][1]["items"][0]["has_active_relations"] is True
    assert [item["existing_asset_id"] for item in result["items"]] == ["old-image", "old-label"]


def test_upload_requests_have_no_file_count_limit():
    files = [
        {"filename": f"{index}.jpg", "size": 1, "mime_type": "image/jpeg", "asset_type": "image"}
        for index in range(159)
    ]
    assert len(assets.UploadConflictCheckRequest(files=files).files) == 159
    assert len(assets.UploadBatchInitRequest(files=files).files) == 159
    assert len(assets.UploadBatchCompleteRequest(upload_session_ids=[f"s-{index}" for index in range(159)]).upload_session_ids) == 159


def test_upload_rejects_unresolved_name_conflict(monkeypatch):
    async def matches(filename, asset_type):
        return [{"id": "old", "name": filename, "type": asset_type}]

    monkeypatch.setattr(assets, "matching_name_assets", matches)
    body = assets.UploadInitRequest(
        filename="same.jpg", size=10, mime_type="image/jpeg", asset_type="image"
    )
    try:
        asyncio.run(assets.initialize_upload(body, {"id": "user"}))
    except AppError as exc:
        assert exc.code == "ASSET_NAME_CONFLICT"
    else:
        raise AssertionError("同名文件必须先选择处理方式")


def test_upload_rename_selects_first_available_suffix(monkeypatch):
    inserted = {}

    async def matches(filename, asset_type):
        if filename in {"same.jpg", "same (1).jpg"}:
            return [{"id": filename, "name": filename, "type": asset_type}]
        return []

    class UploadSessions:
        async def insert_one(self, document):
            inserted.update(document)

    monkeypatch.setattr(assets, "matching_name_assets", matches)
    monkeypatch.setattr(
        assets,
        "db",
        SimpleNamespace(
            assets=SimpleNamespace(find_one=AsyncMock(return_value=None)),
            upload_sessions=UploadSessions(),
        ),
    )
    monkeypatch.setattr(assets, "presigned_put", lambda key: "upload-url")
    body = assets.UploadInitRequest(
        filename="same.jpg",
        size=10,
        mime_type="image/jpeg",
        asset_type="image",
        name_conflict="rename",
    )

    result = asyncio.run(assets.initialize_upload(body, {"id": "user"}))

    assert inserted["filename"] == "same (2).jpg"
    assert result["overwrite_asset_id"] is None


def test_upload_overwrite_keeps_original_asset_id(monkeypatch):
    inserted = {}

    async def matches(filename, asset_type):
        return [{"id": "original-asset", "name": filename, "type": asset_type}]

    class UploadSessions:
        async def insert_one(self, document):
            inserted.update(document)

    monkeypatch.setattr(assets, "matching_name_assets", matches)
    monkeypatch.setattr(
        assets,
        "db",
        SimpleNamespace(
            assets=SimpleNamespace(find_one=AsyncMock(return_value=None)),
            upload_sessions=UploadSessions(),
        ),
    )
    monkeypatch.setattr(assets, "presigned_put", lambda key: "upload-url")
    body = assets.UploadInitRequest(
        filename="same.jpg",
        size=10,
        mime_type="image/jpeg",
        asset_type="image",
        name_conflict="overwrite",
    )

    result = asyncio.run(assets.initialize_upload(body, {"id": "user"}))

    assert inserted["overwrite_asset_id"] == "original-asset"
    assert result["overwrite_asset_id"] == "original-asset"


def test_complete_overwrite_replaces_current_asset_and_preserves_metadata(monkeypatch):
    replaced = {}
    session = {
        "id": "session-1",
        "asset_id": "temporary-id",
        "filename": "same.jpg",
        "declared_size": 12,
        "mime_type": "image/jpeg",
        "asset_type": "image",
        "project": "未分类",
        "sha256": None,
        "object_key": "projects/new/original",
        "duplicate_asset_id": None,
        "overwrite_asset_id": "original-asset",
        "owner_id": "user",
        "state": "reused",
        "transfer_mode": "single",
        "expires_at": assets.now() + assets.timedelta(hours=1),
    }
    original = {
        "id": "original-asset",
        "name": "same.jpg",
        "type": "image",
        "created_at": assets.now(),
        "tags": {"status": ["已标注"]},
        "remark": "保留备注",
        "archived_at": None,
    }

    class AssetStore:
        async def find_one(self, query):
            return original

        async def replace_one(self, query, document):
            replaced.update(document)

    monkeypatch.setattr(
        assets,
        "db",
        SimpleNamespace(
            upload_sessions=SimpleNamespace(
                find_one=AsyncMock(return_value=session), update_one=AsyncMock()
            ),
            assets=AssetStore(),
            jobs=SimpleNamespace(insert_one=AsyncMock(), update_one=AsyncMock()),
        ),
    )
    monkeypatch.setattr(assets, "record_audit", AsyncMock())
    monkeypatch.setattr(assets, "celery_client", SimpleNamespace(send_task=lambda *args, **kwargs: None))
    request = SimpleNamespace(state=SimpleNamespace(request_id="test"))

    result = asyncio.run(
        assets.complete_upload(
            assets.UploadCompleteRequest(upload_session_id="session-1"),
            request,
            {"id": "user", "username": "测试用户"},
        )
    )

    assert result["id"] == "original-asset"
    assert replaced["object_key"] == "projects/new/original"
    assert replaced["tags"] == {"status": ["已标注"]}
    assert replaced["remark"] == "保留备注"
