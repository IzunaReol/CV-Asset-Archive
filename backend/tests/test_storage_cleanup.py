from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from app import storage as storage_module


def test_delete_orphan_chunks_keeps_active_and_recent_objects(monkeypatch):
    timestamp = datetime.now(UTC)
    objects = [
        SimpleNamespace(object_name="uploads/active/00000", last_modified=timestamp - timedelta(days=2)),
        SimpleNamespace(object_name="uploads/expired/00000", last_modified=timestamp - timedelta(days=2)),
        SimpleNamespace(object_name="uploads/recent/00000", last_modified=timestamp - timedelta(minutes=5)),
    ]
    removed = []
    fake_storage = SimpleNamespace(
        list_objects=lambda *args, **kwargs: objects,
        remove_object=lambda bucket, name: removed.append(name),
    )
    monkeypatch.setattr(storage_module, "storage", fake_storage)

    count = storage_module.delete_orphan_chunks({"active"}, timestamp - timedelta(hours=24))

    assert count == 1
    assert removed == ["uploads/expired/00000"]


def test_uploaded_chunks_ignores_non_numeric_objects(monkeypatch):
    objects = [
        SimpleNamespace(object_name="uploads/session/00000", size=10),
        SimpleNamespace(object_name="uploads/session/notes", size=5),
    ]
    monkeypatch.setattr(
        storage_module,
        "storage",
        SimpleNamespace(list_objects=lambda *args, **kwargs: objects),
    )

    assert storage_module.uploaded_chunks("uploads/session/") == {0: 10}


def test_read_object_closes_response(monkeypatch):
    response = SimpleNamespace(read=lambda: b"data", close=lambda: None, release_conn=lambda: None)
    response.close = Mock()
    response.release_conn = Mock()
    monkeypatch.setattr(
        storage_module,
        "storage",
        SimpleNamespace(
            stat_object=lambda *args: SimpleNamespace(size=4),
            get_object=lambda *args: response,
        ),
    )

    assert storage_module.read_object("annotations/a.txt") == b"data"
    response.close.assert_called_once()
    response.release_conn.assert_called_once()


def test_read_object_rejects_oversized_preview(monkeypatch):
    monkeypatch.setattr(
        storage_module,
        "storage",
        SimpleNamespace(stat_object=lambda *args: SimpleNamespace(size=11)),
    )

    try:
        storage_module.read_object("annotations/a.txt", max_bytes=10)
    except ValueError as error:
        assert "超过在线预览解析限制" in str(error)
    else:
        raise AssertionError("oversized object should be rejected")
