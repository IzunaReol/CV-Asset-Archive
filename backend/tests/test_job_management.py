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
