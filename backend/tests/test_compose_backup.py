import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "compose-backup.py"
SPEC = importlib.util.spec_from_file_location("compose_backup", SCRIPT)
assert SPEC and SPEC.loader
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


def test_manifest_ignores_its_own_file_and_detects_changed_content(tmp_path):
    (tmp_path / "mongo.archive.gz").write_bytes(b"database")
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    original = backup.file_manifest(tmp_path)
    assert set(original) == {"mongo.archive.gz"}
    (tmp_path / "mongo.archive.gz").write_bytes(b"changed")
    assert backup.file_manifest(tmp_path) != original


def test_restore_requires_explicit_new_project_confirmation(tmp_path):
    with pytest.raises(ValueError, match="--confirm-new-project"):
        backup.restore("existing-project", tmp_path, False)


@pytest.mark.parametrize("backup_fails", [False, True])
def test_backup_restarts_existing_containers_without_pull(monkeypatch, tmp_path, backup_fails):
    calls = []

    def fake_compose(project, *args, capture=False):
        assert project == "cv-archive"
        calls.append(args)
        if args[:3] == ("ps", "--status", "running"):
            return "mongodb\nminio\napi\nworker"
        if args == ("ps", "-q", "minio"):
            return "minio-container"
        return ""

    def fake_stream(destination, command):
        if backup_fails:
            raise RuntimeError("dump failed")
        destination.write_bytes(b"mongo archive")

    def fake_run(*args, capture=False):
        assert args[:2] == ("docker", "cp")
        (destination / "minio" / "object").write_bytes(b"asset")
        return ""

    monkeypatch.setattr(backup, "compose", fake_compose)
    monkeypatch.setattr(backup, "stream_command", fake_stream)
    monkeypatch.setattr(backup, "run", fake_run)
    destination = tmp_path / "backup"
    if backup_fails:
        with pytest.raises(RuntimeError, match="dump failed"):
            backup.backup("cv-archive", destination)
    else:
        backup.backup("cv-archive", destination)
        assert (destination / "manifest.json").is_file()

    assert ("stop", "api", "worker") in calls
    assert calls[-1] == ("start", "api", "worker")
    assert not any(call[0] == "up" for call in calls)
