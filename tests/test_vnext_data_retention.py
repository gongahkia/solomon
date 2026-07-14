from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from stonks_cli.vnext.data_retention import DataRetentionPolicy, enforce_data_retention

NOW = datetime(2026, 7, 14, 3, tzinfo=UTC)


def test_data_retention_deletes_only_expired_unprotected_regular_files(tmp_path):
    old_path = _write_with_mtime(tmp_path / "old.json", NOW - timedelta(days=31))
    protected_path = _write_with_mtime(tmp_path / "ledger.json", NOW - timedelta(days=31))
    fresh_path = _write_with_mtime(tmp_path / "nested" / "fresh.json", NOW - timedelta(days=1))

    report = enforce_data_retention(
        tmp_path,
        DataRetentionPolicy(timedelta(days=30), frozenset({"ledger.json"})),
        NOW,
    )

    assert report.deleted_relative_paths == ("old.json",)
    assert report.retained_relative_paths == ("ledger.json", "nested/fresh.json")
    assert old_path.exists() is False
    assert protected_path.exists() is True
    assert fresh_path.exists() is True


def test_data_retention_fails_closed_for_missing_or_malformed_policy(tmp_path):
    with pytest.raises(TypeError, match="data-retention"):
        enforce_data_retention(tmp_path, None, NOW)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="protected paths"):
        DataRetentionPolicy(timedelta(days=1), frozenset({"../outside"}))


def test_data_retention_fails_closed_without_mutating_when_root_contains_a_symlink(tmp_path):
    old_path = _write_with_mtime(tmp_path / "old.json", NOW - timedelta(days=31))
    (tmp_path / "linked.json").symlink_to(old_path)

    with pytest.raises(ValueError, match="must not contain symlinks"):
        enforce_data_retention(tmp_path, DataRetentionPolicy(timedelta(days=30)), NOW)

    assert old_path.exists() is True


@pytest.mark.parametrize("max_age", [timedelta(), timedelta(days=-1), "30 days"])
def test_data_retention_policy_rejects_invalid_age(max_age):
    with pytest.raises(ValueError, match="maximum age"):
        DataRetentionPolicy(max_age)  # type: ignore[arg-type]


def _write_with_mtime(path, timestamp: datetime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture", encoding="utf-8")
    os.utime(path, (timestamp.timestamp(), timestamp.timestamp()))
    return path
