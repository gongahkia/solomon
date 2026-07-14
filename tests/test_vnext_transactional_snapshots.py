from datetime import UTC, datetime
from uuid import UUID

import pytest

from stonks_cli.vnext.database import SQLiteConnectionFactory
from stonks_cli.vnext.errors import VNextInvariantError
from stonks_cli.vnext.transactional_snapshots import TransactionalSnapshot, TransactionalSnapshotStore


def test_transactional_snapshot_store_commits_a_complete_batch(tmp_path):
    store = TransactionalSnapshotStore(SQLiteConnectionFactory(tmp_path / "snapshots.sqlite3"))
    first = _snapshot("00000000-0000-4000-8000-000000000001", "research.universe", {"count": 1})
    second = _snapshot("00000000-0000-4000-8000-000000000002", "portfolio.state", {"count": 2})

    store.write_batch((first, second))

    assert TransactionalSnapshotStore(store.factory).load(first.snapshot_id) == first
    assert store.load(second.snapshot_id) == second


def test_transactional_snapshot_store_rolls_back_the_full_batch_on_conflict_or_sensitive_payload(tmp_path):
    store = TransactionalSnapshotStore(SQLiteConnectionFactory(tmp_path / "snapshots.sqlite3"))
    first = _snapshot("00000000-0000-4000-8000-000000000001", "research.universe", {"count": 1})
    second = _snapshot("00000000-0000-4000-8000-000000000002", "portfolio.state", {"count": 2})
    store.write_batch((first,))

    with pytest.raises(VNextInvariantError, match="could not commit"):
        store.write_batch((first, second))
    assert store.load(second.snapshot_id) is None
    with pytest.raises(ValueError, match="sensitive"):
        _snapshot("00000000-0000-4000-8000-000000000003", "portfolio.state", {"api_token": "secret"})


def _snapshot(snapshot_id: str, kind: str, payload: dict[str, object]) -> TransactionalSnapshot:
    return TransactionalSnapshot(UUID(snapshot_id), kind, datetime(2026, 7, 14, 2, tzinfo=UTC), payload)
