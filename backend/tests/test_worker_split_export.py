import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from worker import tasks


def test_asset_export_includes_snapshotted_annotation_once(monkeypatch, tmp_path):
    job = {"id": "job", "type": "export", "name": "素材导出", "input": {
        "asset_ids": ["image-1", "annotation-1"],
        "annotation_ids": ["annotation-1"],
    }}
    assets = [
        {"id": "image-1", "name": "a.jpg", "object_key": "image-1"},
        {"id": "annotation-1", "name": "a.txt", "object_key": "annotation-1"},
    ]
    jobs = SimpleNamespace(find_one=MagicMock(return_value=job), update_one=MagicMock(return_value=SimpleNamespace(modified_count=1)))
    saved = {}
    collection = SimpleNamespace(
        count_documents=MagicMock(return_value=2),
        find=MagicMock(return_value=assets),
    )
    monkeypatch.setattr(tasks, "database", SimpleNamespace(jobs=jobs, assets=collection))
    monkeypatch.setattr(tasks, "storage", SimpleNamespace(
        get_object=lambda bucket, key: SimpleNamespace(
            stream=lambda size: iter([key.encode()]), close=lambda: None, release_conn=lambda: None,
        ),
        fput_object=lambda bucket, key, filename, content_type: saved.update(data=Path(filename).read_bytes()),
    ))
    monkeypatch.setattr(tasks, "WORKER_TEMP_DIR", tmp_path)
    tasks.build_export.run.__wrapped__("job")
    assert collection.find.call_args.args[0]["id"]["$in"] == ["image-1", "annotation-1"]
    with zipfile.ZipFile(io.BytesIO(saved["data"])) as archive:
        assert set(archive.namelist()) == {"a.jpg", "a.txt"}


def test_worker_writes_flat_dataset_export_and_frozen_names(monkeypatch, tmp_path):
    job = {"id": "job", "type": "dataset_export", "name": "烟火 v2 全部导出", "input": {
        "asset_ids": ["image", "annotation", "video"],
        "entries": [
            {"asset_id": "image", "name": "old.jpg", "folder": ""},
            {"asset_id": "annotation", "name": "old.txt", "folder": ""},
            {"asset_id": "video", "name": "sample.mp4", "folder": ""},
        ],
    }}
    assets = [
        {"id": "image", "name": "renamed.jpg", "object_key": "image"},
        {"id": "annotation", "name": "renamed.txt", "object_key": "annotation"},
        {"id": "video", "name": "sample.mp4", "object_key": "video"},
    ]
    jobs = SimpleNamespace(find_one=MagicMock(return_value=job), update_one=MagicMock(return_value=SimpleNamespace(modified_count=1)))
    database = SimpleNamespace(jobs=jobs, assets=SimpleNamespace(count_documents=MagicMock(return_value=3), find=MagicMock(return_value=assets)))
    saved = {}

    def get_object(bucket, key):
        return SimpleNamespace(stream=lambda size: iter([key.encode()]), close=lambda: None, release_conn=lambda: None)

    def save_object(bucket, key, filename, content_type):
        saved["bytes"] = Path(filename).read_bytes()
        saved["key"] = key

    monkeypatch.setattr(tasks, "database", database)
    monkeypatch.setattr(tasks, "storage", SimpleNamespace(get_object=get_object, fput_object=save_object))
    monkeypatch.setattr(tasks, "WORKER_TEMP_DIR", tmp_path)
    tasks.build_export.run.__wrapped__("job")

    assert saved["key"].endswith("烟火 v2 全部导出.zip")
    with zipfile.ZipFile(io.BytesIO(saved["bytes"])) as archive:
        assert set(archive.namelist()) == {"old.jpg", "old.txt", "sample.mp4"}


def test_worker_accepts_custom_category_and_unclassified_dataset(monkeypatch, tmp_path):
    category = "正常"
    job = {"id": "job", "type": "dataset_export", "name": "分类导出", "input": {
        "asset_ids": ["a", "b"], "entries": [
            {"asset_id": "a", "name": "one.jpg", "folder": category},
            {"asset_id": "b", "name": "two.jpg", "folder": "未划分"},
        ],
    }}
    assets = [{"id": key, "name": f"{key}.jpg", "object_key": key} for key in ("a", "b")]
    jobs = SimpleNamespace(find_one=MagicMock(return_value=job), update_one=MagicMock(return_value=SimpleNamespace(modified_count=1)))
    saved = {}
    monkeypatch.setattr(tasks, "database", SimpleNamespace(jobs=jobs, assets=SimpleNamespace(count_documents=MagicMock(return_value=2), find=MagicMock(return_value=assets))))
    monkeypatch.setattr(tasks, "storage", SimpleNamespace(get_object=lambda bucket, key: SimpleNamespace(stream=lambda size: iter([key.encode()]), close=lambda: None, release_conn=lambda: None), fput_object=lambda bucket, key, filename, content_type: saved.update(data=Path(filename).read_bytes())))
    monkeypatch.setattr(tasks, "WORKER_TEMP_DIR", tmp_path)
    tasks.build_export.run.__wrapped__("job")
    with zipfile.ZipFile(io.BytesIO(saved["data"])) as archive:
        assert set(archive.namelist()) == {f"{category}/one.jpg", "未划分/two.jpg"}
