import asyncio
from types import SimpleNamespace

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
