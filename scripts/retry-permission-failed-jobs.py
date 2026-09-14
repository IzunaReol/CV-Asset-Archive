"""Requeue asset processing jobs that failed because the worker could not write temp files."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from celery import Celery
from pymongo import MongoClient


def main() -> None:
    mongo_uri = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017")
    database_name = os.getenv("MONGODB_DATABASE", "cv_archive")
    redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    database = MongoClient(mongo_uri, tz_aware=True)[database_name]
    celery = Celery(broker=redis_url)
    jobs = list(
        database.jobs.find(
            {
                "type": "process_asset",
                "state": "failed",
                "error.code": "PROCESS_PERMISSION_DENIED",
            }
        )
    )
    submitted = 0
    for job in jobs:
        asset_id = job.get("input", {}).get("asset_id")
        if not asset_id or database.assets.find_one({"id": asset_id}) is None:
            continue
        timestamp = datetime.now(UTC)
        database.jobs.update_one(
            {"id": job["id"], "state": "failed"},
            {
                "$set": {
                    "state": "queued",
                    "progress": 0,
                    "error": None,
                    "updated_at": timestamp,
                },
                "$inc": {"attempt": 1},
            },
        )
        database.assets.update_one(
            {"id": asset_id},
            {
                "$set": {
                    "status": "processing",
                    "processing_error": None,
                    "modified_at": timestamp,
                }
            },
        )
        celery.send_task("worker.tasks.process_asset", args=[job["id"], asset_id])
        submitted += 1
    print(f"Requeued {submitted} permission-failed processing jobs.")


if __name__ == "__main__":
    main()
