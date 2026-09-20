"""Run a disposable end-to-end API check against an isolated database."""

from __future__ import annotations

import json
import os
import io
import time
import urllib.error
import urllib.request
from typing import Any

from minio import Minio
from PIL import Image
from pymongo import MongoClient


BASE_URL = os.getenv("E2E_API_URL", "http://127.0.0.1:8010/api/v1")
DATABASE = os.getenv("MONGODB_DATABASE", "cv_archive_e2e")


def request(path: str, method: str = "GET", body: Any = None, token: str = "") -> Any:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {path}: {exc.code} {exc.read().decode()}") from exc


def upload(token: str, filename: str, content: bytes, asset_type: str) -> dict[str, Any]:
    session = request(
        "/assets/upload-sessions",
        "POST",
        {
            "filename": filename,
            "size": len(content),
            "mime_type": "application/octet-stream",
            "asset_type": asset_type,
            "project": "e2e-isolated",
        },
        token,
    )
    put = urllib.request.Request(session["upload_url"], data=content, method="PUT")
    with urllib.request.urlopen(put, timeout=20):
        pass
    return request(
        "/assets/upload-sessions/complete",
        "POST",
        {"upload_session_id": session["upload_session_id"], "tags": {}},
        token,
    )


def main() -> None:
    if not DATABASE.startswith("cv_archive_e2e") or "8010" not in BASE_URL:
        raise RuntimeError("E2E requires an isolated database and API port 8010")
    login = request("/auth/login", "POST", {"username": "admin", "password": "admin"})
    token = login["access_token"]
    pixels = io.BytesIO()
    Image.new("RGB", (48, 32), (120, 80, 40)).save(pixels, format="JPEG")
    image = upload(token, "pair.JPG", pixels.getvalue(), "image")
    annotation = upload(token, "pair.txt", b"0 0.5 0.5 0.2 0.2\n", "annotation")
    model = upload(token, "model.onnx", b"e2e-model", "model")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        states = [request(f"/assets/{item['id']}", token=token)["status"] for item in (image, annotation, model)]
        if all(state == "ready" for state in states):
            break
        if any(state == "failed" for state in states):
            raise RuntimeError(f"Asset processing failed: {states}")
        time.sleep(0.3)
    else:
        raise RuntimeError("Asset processing timed out")

    auto = request(
        "/relations/annotation-match-preview",
        "POST",
        {"image_ids": [image["id"]], "annotation_ids": [annotation["id"]]},
        token,
    )
    assert auto["counts"]["ready"] == 1
    auto_create = request(
        "/relations/batch",
        "POST",
        {
            "relations": [
                {
                    "source_id": annotation["id"],
                    "target_id": image["id"],
                    "relation_type": "annotates",
                    "provenance": {"source": "e2e"},
                }
            ]
        },
        token,
    )
    assert len(auto_create["succeeded"]) == 1

    dataset = request("/datasets", "POST", {"name": "e2e-dataset"}, token)
    members = request(f"/datasets/{dataset['id']}/members", "POST", {"asset_ids": [image["id"]]}, token)
    assert members["added"] == 1 and annotation["id"] in members["annotations"]["added"]
    version = request(f"/datasets/{dataset['id']}/versions", "POST", {"version": "v1", "release_note": "e2e"}, token)
    assert version["member_count"] == 2
    model_body = {
        "relations": [
            {
                "source_id": model["id"],
                "target_id": version["id"],
                "relation_type": "trained_on",
                "provenance": {"source": "dataset", "dataset_id": dataset["id"], "dataset_version_id": version["id"]},
            }
        ]
    }
    model_preview = request("/relations/preview", "POST", model_body, token)
    assert model_preview["counts"]["ready"] == 1
    model_create = request("/relations/batch", "POST", model_body, token)
    model_relation = model_create["succeeded"][0]
    repeated = request("/relations/preview", "POST", model_body, token)
    assert repeated["counts"]["existing"] == 1
    graph = request(f"/relations/graph/{model['id']}?depth=4", token=token)
    model_edges = [
        edge
        for edge in graph["edges"]
        if edge["source_id"] == model["id"] and edge["relation_type"] == "trained_on"
    ]
    assert len(model_edges) == 1 and model_edges[0]["target_id"] == version["id"]
    assert any(edge.get("derived") and edge.get("target_id") == image["id"] for edge in graph["edges"])
    history = request("/relations?page=1&page_size=10&created_by=admin&status=active", token=token)
    assert history["total"] == 2
    request(
        f"/relations/{model_relation['id']}/revoke",
        "POST",
        {"reason": "自动化测试完成"},
        token,
    )
    graph_after = request(f"/relations/graph/{model['id']}?depth=4", token=token)
    assert len(graph_after["edges"]) == 0
    if os.getenv("E2E_KEEP") == "1":
        recreated = request("/relations/batch", "POST", model_body, token)
        assert len(recreated["succeeded"]) == 1

    duplicate = upload(token, "PAIR.png", pixels.getvalue(), "image")
    conflict = request(
        "/relations/annotation-match-preview",
        "POST",
        {"image_ids": [image["id"], duplicate["id"]], "annotation_ids": [annotation["id"]]},
        token,
    )
    assert conflict["counts"]["image_conflicts"] == 1
    mismatch = request(
        "/relations/preview",
        "POST",
        {
            "relations": [
                {
                    "source_id": image["id"],
                    "target_id": annotation["id"],
                    "relation_type": "annotates",
                }
            ]
        },
        token,
    )
    assert mismatch["invalid"][0]["code"] == "RELATION_TYPE_MISMATCH"
    filtered = request("/assets?page=1&page_size=20&q=pair&asset_type=image", token=token)
    assert filtered["total"] == 2
    print(json.dumps({
        "uploads": 4,
        "dataset_version_members": version["member_count"],
        "auto_match_ready": auto["counts"]["ready"],
        "duplicate_conflicts": conflict["counts"]["image_conflicts"],
        "model_graph_edges": len(model_edges),
        "graph_edges_after_revoke": len(graph_after["edges"]),
        "history_active": history["total"],
        "type_validation": mismatch["invalid"][0]["code"],
    }, ensure_ascii=False))


def cleanup() -> None:
    if not DATABASE.startswith("cv_archive_e2e"):
        raise RuntimeError("Refusing to clean a non-E2E database")
    mongo = MongoClient(os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017"))
    database = mongo[DATABASE]
    objects = {
        key
        for item in database.assets.find({}, {"object_key": 1, "preview_key": 1})
        for key in (item.get("object_key"), item.get("preview_key"))
        if key
    }
    client = Minio(
        os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000"),
        access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        secure=False,
    )
    for object_key in objects:
        try:
            client.remove_object(os.getenv("MINIO_BUCKET", "cv-assets"), object_key)
        except Exception:
            pass
    mongo.drop_database(DATABASE)
    mongo.close()


if __name__ == "__main__":
    if os.getenv("E2E_CLEANUP_ONLY") == "1":
        cleanup()
    else:
        try:
            main()
        finally:
            if os.getenv("E2E_KEEP") != "1":
                cleanup()
