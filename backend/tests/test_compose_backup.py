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
