import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from worker import tasks


def test_worker_writes_split_directories_and_frozen_names(monkeypatch, tmp_path):
    job = {"id": "job", "type": "dataset_export", "name": "烟火 v2 全部导出", "input": {
        "asset_ids": ["image", "annotation", "video"],
        "entries": [
            {"asset_id": "image", "name": "old.jpg", "folder": "train"},
            {"asset_id": "annotation", "name": "old.txt", "folder": "train"},
            {"asset_id": "video", "name": "sample.mp4", "folder": "other"},
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
        assert set(archive.namelist()) == {"train/old.jpg", "train/old.txt", "other/sample.mp4"}
