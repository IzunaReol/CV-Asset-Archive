from scripts.verify_migrations import has_mismatch


def test_migration_report_accepts_matching_dataset():
    assert not has_mismatch(
        {
            "dataset_exists": True,
            "missing_members": [],
            "unexpected_members": [],
        }
    )


def test_migration_report_rejects_missing_version_member():
    assert has_mismatch(
        {
            "dataset_exists": True,
            "missing_members": [],
            "unexpected_members": [],
            "version_exists": True,
            "missing_version_members": ["asset-1"],
            "unexpected_version_members": [],
            "current_version_matches": True,
        }
    )


def test_migration_report_skips_intentionally_deleted_dataset():
    assert not has_mismatch(
        {
            "dataset_exists": True,
            "missing_members": [],
            "unexpected_members": [],
            "version_exists": False,
            "current_version_matches": False,
            "skipped_reason": "数据集已删除",
        }
    )
