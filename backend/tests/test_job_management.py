import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.errors import AppError
from app.routers import jobs


class AsyncRows:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, length=None):
        return self.rows

    def sort(self, *args):
        return self

    def skip(self, *args):
        return self

    def limit(self, *args):
        return self

    def __aiter__(self):
        self.iterator = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration:
            raise StopAsyncIteration


def test_task_center_excludes_asset_processing_jobs(monkeypatch):
    def find(*args, **kwargs):
        return AsyncRows([])
    database = SimpleNamespace(
        jobs=SimpleNamespace(count_documents=AsyncMock(return_value=0), find=find)
    )
    monkeypatch.setattr(jobs, "db", database)

    result = asyncio.run(jobs.list_jobs(
        {"id": "admin", "roles": ["admin"]}, page=1, page_size=20,
        job_type=None, state=None, created_from=None, created_to=None, download_only=False,
    ))

    query = database.jobs.count_documents.call_args.args[0]
    assert query["type"] == {"$in": ["export", "dataset_export", "trash_empty"]}
    assert result["items"] == []


def test_task_center_backfills_export_file_size(monkeypatch):
    job = {
        "id": "job-1",
        "type": "export",
        "state": "succeeded",
        "result": {"object_key": "exports/job-1/archive.zip"},
    }
    update_one = AsyncMock(return_value=SimpleNamespace(modified_count=1))
    database = SimpleNamespace(
        jobs=SimpleNamespace(
            find=lambda *args, **kwargs: AsyncRows([job]),
            update_one=update_one,
        )
    )
    monkeypatch.setattr(jobs, "db", database)
    monkeypatch.setattr(jobs, "stat_object", lambda object_key: SimpleNamespace(size=3145728))

    result = asyncio.run(jobs.backfill_export_sizes())

    assert result == 1
    update_one.assert_awaited_once_with(
        {"id": "job-1", "result.size": {"$exists": False}},
        {"$set": {"result.size": 3145728}},
    )


def test_task_center_backfill_continues_when_write_fails(monkeypatch):
    job = {
        "id": "job-1",
        "type": "export",
        "state": "succeeded",
        "result": {"object_key": "exports/job-1/archive.zip"},
    }
    database = SimpleNamespace(
        jobs=SimpleNamespace(
            find=lambda *args, **kwargs: AsyncRows([job]),
            update_one=AsyncMock(side_effect=RuntimeError("database unavailable")),
        )
    )
    monkeypatch.setattr(jobs, "db", database)
    monkeypatch.setattr(jobs, "stat_object", lambda object_key: SimpleNamespace(size=1024))

    result = asyncio.run(jobs.backfill_export_sizes())

    assert result == 0


def test_task_center_listing_does_not_read_object_storage(monkeypatch):
    job = {
        "id": "job-1",
        "type": "export",
        "state": "succeeded",
        "result": {"object_key": "exports/job-1/archive.zip"},
    }
    database = SimpleNamespace(
        jobs=SimpleNamespace(
            count_documents=AsyncMock(return_value=1),
            find=lambda *args, **kwargs: AsyncRows([job]),
        )
    )
    monkeypatch.setattr(jobs, "db", database)
    monkeypatch.setattr(
        jobs, "stat_object", lambda object_key: (_ for _ in ()).throw(AssertionError())
    )

    result = asyncio.run(jobs.list_jobs(
        {"id": "admin", "roles": ["admin"]}, page=1, page_size=20,
        job_type=None, state=None, created_from=None, created_to=None, download_only=False,
    ))

    assert "size" not in result["items"][0]["result"]


def test_cancel_export_is_scoped_to_owner_and_audited(monkeypatch):
    update = AsyncMock(return_value=SimpleNamespace(modified_count=1))
    stored = {"id": "job-1", "type": "export", "state": "cancelled"}
    database = SimpleNamespace(
        jobs=SimpleNamespace(update_one=update, find_one=AsyncMock(return_value=stored))
    )
    audit = AsyncMock()
    monkeypatch.setattr(jobs, "db", database)
    monkeypatch.setattr(jobs, "record_audit", audit)

    result = asyncio.run(
        jobs.cancel_job(
            "job-1",
            SimpleNamespace(state=SimpleNamespace(request_id="request-1")),
            {"id": "user-1", "roles": ["viewer"]},
        )
    )

    query = update.call_args.args[0]
    assert query["owner_id"] == "user-1"
    assert query["type"] == {"$in": ["dataset_export", "export"]}
    assert result["state"] == "cancelled"
    assert audit.call_args.kwargs["action"] == "job.cancelled"


def test_cancel_rejects_finished_or_non_cancellable_job(monkeypatch):
    database = SimpleNamespace(
        jobs=SimpleNamespace(
            update_one=AsyncMock(return_value=SimpleNamespace(modified_count=0)),
            find_one=AsyncMock(),
        )
    )
    monkeypatch.setattr(jobs, "db", database)

    with pytest.raises(AppError) as error:
        asyncio.run(
            jobs.cancel_job(
                "job-1",
                SimpleNamespace(state=SimpleNamespace(request_id="request-1")),
                {"id": "admin", "roles": ["admin"]},
            )
        )
    assert error.value.code == "JOB_NOT_CANCELLABLE"


def test_retry_empty_trash_uses_correct_worker_task(monkeypatch):
    failed = {
        "id": "job-1",
        "type": "trash_empty",
        "state": "failed",
        "owner_id": "admin",
        "input": {},
    }
    refreshed = {**failed, "state": "queued", "attempt": 1}
    database = SimpleNamespace(
        jobs=SimpleNamespace(
            find_one=AsyncMock(side_effect=[failed, refreshed]),
            update_one=AsyncMock(return_value=SimpleNamespace(modified_count=1)),
        ),
        assets=SimpleNamespace(update_one=AsyncMock()),
    )
    dispatch = AsyncMock()
    monkeypatch.setattr(jobs, "db", database)
    monkeypatch.setattr(jobs, "_dispatch_job", dispatch)

    result = asyncio.run(jobs.retry_job("job-1", {"id": "admin", "roles": ["admin"]}))

    dispatch.assert_awaited_once_with(failed)
    assert result["state"] == "queued"


def test_reconcile_stale_jobs_marks_jobs_and_assets_failed(monkeypatch):
    stale = [
        {"id": "job-1", "type": "process_asset", "input": {"asset_id": "asset-1"}},
        {"id": "job-2", "type": "export", "input": {}},
    ]
    database = SimpleNamespace(
        jobs=SimpleNamespace(
            find=lambda *args: AsyncRows(stale),
            update_many=AsyncMock(),
        ),
        assets=SimpleNamespace(update_many=AsyncMock()),
    )
    monkeypatch.setattr(jobs, "db", database)

    count = asyncio.run(jobs.reconcile_stale_jobs())

    assert count == 2
    job_update = database.jobs.update_many.call_args.args[1]["$set"]
    assert job_update["error"]["code"] == "TASK_INTERRUPTED"
    asset_query = database.assets.update_many.call_args.args[0]
    assert asset_query["id"] == {"$in": ["asset-1"]}
