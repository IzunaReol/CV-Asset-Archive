"""Verify a resumable near-limit upload against an isolated API deployment."""

from __future__ import annotations

import argparse
import json
import socket
import time
import urllib.error
import urllib.request

from minio import Minio
from pymongo import MongoClient


def api_request(
    base_url: str,
    path: str,
    method: str = "GET",
    body=None,
    token: str = "",
    timeout: int = 60,
):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            return json.loads(payload) if payload else None
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {path}: {exc.code} {exc.read().decode()}") from exc


def put_chunk(url: str, content: memoryview, attempts: int = 5) -> None:
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, data=content, method="PUT")
            with urllib.request.urlopen(request, timeout=180):
                return
        except (TimeoutError, socket.timeout, urllib.error.URLError):
            if attempt == attempts:
                raise
            time.sleep(min(2**attempt, 10))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8010/api/v1")
    parser.add_argument("--size-gib", type=float, default=10.0)
    parser.add_argument("--database", default="cv_archive_e2e_large_upload")
    parser.add_argument("--bucket", default="cv-assets-e2e-large-upload")
    parser.add_argument("--mongo-uri", default="mongodb://127.0.0.1:27017")
    parser.add_argument("--minio-endpoint", default="127.0.0.1:9000")
    args = parser.parse_args()
    if not args.database.startswith("cv_archive_e2e") or "8010" not in args.base_url:
        parser.error("large upload verification requires an isolated database and API port 8010")

    declared_size = int(args.size_gib * 1024**3)
    mongo = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=3000)
    minio = Minio(args.minio_endpoint, access_key="minioadmin", secret_key="minioadmin", secure=False)
    started = time.perf_counter()
    try:
        login = api_request(args.base_url, "/auth/login", "POST", {"username": "admin", "password": "admin"})
        token = login["access_token"]
        session = api_request(
            args.base_url,
            "/assets/upload-sessions",
            "POST",
            {
                "filename": f"acceptance-{args.size_gib:g}GiB.bin",
                "size": declared_size,
                "mime_type": "application/octet-stream",
                "asset_type": "other",
                "project": "release-acceptance",
            },
            token,
        )
        session_id = session["upload_session_id"]
        status = api_request(args.base_url, f"/assets/upload-sessions/{session_id}", token=token)
        chunk_size = status["chunk_size"]
        chunk_count = status["chunk_count"]
        if status["transfer_mode"] != "chunks" or chunk_count < 2:
            raise RuntimeError("large file did not use chunked transfer")
        block = b"\0" * chunk_size

        pause_after = min(3, chunk_count - 1)
        for index in range(pause_after):
            size = min(chunk_size, declared_size - index * chunk_size)
            put_chunk(status["upload_urls"][str(index)], memoryview(block)[:size])
        resumed = api_request(args.base_url, f"/assets/upload-sessions/{session_id}", token=token)
        expected = list(range(pause_after))
        if resumed["uploaded_parts"] != expected:
            raise RuntimeError(f"resume state mismatch: expected {expected}, got {resumed['uploaded_parts']}")
        print(f"resume verified after {pause_after} chunks; {chunk_count} chunks total", flush=True)

        for index in range(pause_after, chunk_count):
            size = min(chunk_size, declared_size - index * chunk_size)
            put_chunk(resumed["upload_urls"][str(index)], memoryview(block)[:size])
            if (index + 1) % 10 == 0 or index + 1 == chunk_count:
                elapsed = time.perf_counter() - started
                print(f"uploaded {index + 1}/{chunk_count} chunks ({(index + 1) * chunk_size / 1024**3:.2f} GiB), {elapsed:.1f}s", flush=True)

        asset = api_request(
            args.base_url,
            "/assets/upload-sessions/complete",
            "POST",
            {"upload_session_id": session_id, "tags": {}},
            token,
            timeout=900,
        )
        if asset["size"] != declared_size:
            raise RuntimeError(f"completed asset size mismatch: {asset['size']} != {declared_size}")
        elapsed = time.perf_counter() - started
        print(json.dumps({
            "result": "passed",
            "declared_bytes": declared_size,
            "chunk_count": chunk_count,
            "chunk_size": chunk_size,
            "resume_parts": expected,
            "elapsed_seconds": round(elapsed, 1),
            "asset_id": asset["id"],
        }, ensure_ascii=False), flush=True)
    finally:
        mongo.drop_database(args.database)
        mongo.close()
        if minio.bucket_exists(args.bucket):
            objects = list(minio.list_objects(args.bucket, recursive=True))
            for item in objects:
                minio.remove_object(args.bucket, item.object_name)
            minio.remove_bucket(args.bucket)


if __name__ == "__main__":
    main()
