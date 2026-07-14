from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from stonks_cli.vnext.database import SQLiteConnectionFactory
from stonks_cli.vnext.single_run_lease import SingleRunLeaseStore


def test_single_run_lease_allows_one_owner_until_expiry_and_blocks_stale_release(tmp_path):
    store = SingleRunLeaseStore(SQLiteConnectionFactory(tmp_path / "leases.sqlite3"))
    first_owner = UUID("00000000-0000-4000-8000-000000000001")
    second_owner = UUID("00000000-0000-4000-8000-000000000002")
    started_at = datetime(2026, 7, 14, 2, tzinfo=UTC)
    first = store.try_acquire("operator.daily_report", first_owner, started_at, timedelta(minutes=1))

    assert first is not None
    assert store.try_acquire("operator.daily_report", second_owner, started_at + timedelta(seconds=30), timedelta(minutes=1)) is None
    replacement = store.try_acquire("operator.daily_report", second_owner, started_at + timedelta(minutes=1), timedelta(minutes=1))
    assert replacement is not None
    assert replacement.owner_id == second_owner
    assert store.renew(first, started_at + timedelta(minutes=1), timedelta(minutes=1)) is None
    assert store.release(first) is False
    assert store.release(replacement) is True


def test_single_run_lease_fails_closed_for_malformed_name_or_duration(tmp_path):
    store = SingleRunLeaseStore(SQLiteConnectionFactory(tmp_path / "leases.sqlite3"))
    owner = UUID("00000000-0000-4000-8000-000000000001")
    now = datetime(2026, 7, 14, 2, tzinfo=UTC)

    with pytest.raises(ValueError, match="name"):
        store.try_acquire("invalid lease", owner, now, timedelta(minutes=1))
    with pytest.raises(ValueError, match="duration"):
        store.try_acquire("operator.daily_report", owner, now, timedelta(0))
