from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from stonks_cli.vnext.reconciliation import ReconciliationPosition, ReconciliationSnapshot


def test_reconciliation_schema_serializes_a_canonical_snapshot():
    snapshot = _snapshot()

    assert ReconciliationSnapshot.from_data(snapshot.to_data()) == snapshot
    assert snapshot.positions == (ReconciliationPosition("US.AAPL", 2.0), ReconciliationPosition("US.MSFT", 1.0))


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"snapshot_id": "00000000-0000-4000-8000-000000000001"},
        {
            "snapshot_id": "00000000-0000-4000-8000-000000000001",
            "source_id": "broker.snapshot",
            "captured_at": "2026-07-14T03:00:00Z",
            "currency": "USD",
            "cash_balance": 10.0,
            "positions": [{"symbol": "US.AAPL", "quantity": "2"}],
        },
    ],
)
def test_reconciliation_schema_fails_closed_for_missing_or_malformed_external_data(data):
    with pytest.raises(ValueError, match="reconciliation snapshot"):
        ReconciliationSnapshot.from_data(data)


@pytest.mark.parametrize(
    "positions",
    [
        (ReconciliationPosition("US.MSFT", 1.0), ReconciliationPosition("US.AAPL", 2.0)),
        (ReconciliationPosition("US.AAPL", 2.0), ReconciliationPosition("US.AAPL", 1.0)),
    ],
)
def test_reconciliation_schema_rejects_noncanonical_positions(positions):
    values = _snapshot().to_data()

    with pytest.raises(ValueError, match="not canonical"):
        ReconciliationSnapshot(
            UUID(values["snapshot_id"]),
            values["source_id"],
            datetime.fromisoformat(values["captured_at"]),
            values["currency"],
            values["cash_balance"],
            positions,
        )


def _snapshot() -> ReconciliationSnapshot:
    return ReconciliationSnapshot(
        UUID("00000000-0000-4000-8000-000000000001"),
        "broker.snapshot",
        datetime(2026, 7, 14, 3, tzinfo=UTC),
        "USD",
        10.0,
        (ReconciliationPosition("US.AAPL", 2.0), ReconciliationPosition("US.MSFT", 1.0)),
    )
