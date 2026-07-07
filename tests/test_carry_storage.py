from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from stonks_cli.whalemirror.carry_storage import CarryStorage, CarryStorageRetentionPolicy
from stonks_cli.whalemirror.models import (
    BasisSnapshot,
    CarryDecision,
    CarryPosition,
    CarryQuote,
    FundingSnapshot,
)


def test_carry_storage_initializes_tables_and_writes_snapshots(tmp_path):
    storage = CarryStorage(tmp_path / "carry.sqlite3")
    storage.initialize()
    _write_full_sample(storage, timestamp="2026-07-09T00:00:00Z")

    assert storage.count_rows("carry_quotes") == 1
    assert storage.count_rows("carry_funding_snapshots") == 1
    assert storage.count_rows("carry_basis_snapshots") == 1
    assert storage.count_rows("carry_decisions") == 1
    assert storage.count_rows("carry_positions") == 1
    assert storage.count_rows("carry_venue_health") == 1


def test_carry_storage_retention_compacts_raw_rows_and_keeps_audit_decisions(tmp_path):
    storage = CarryStorage(tmp_path / "carry.sqlite3")
    storage.initialize()
    _write_full_sample(storage, timestamp="2026-07-01T00:00:00Z", decision_id="carry-old")
    _write_full_sample(storage, timestamp="2026-07-09T00:00:00Z", decision_id="carry-new")

    result = storage.run_retention(
        CarryStorageRetentionPolicy(raw_retention_days=7, aggregate_retention_days=180),
        now=datetime(2026, 7, 10, tzinfo=UTC),
    )
    second = storage.run_retention(
        CarryStorageRetentionPolicy(raw_retention_days=7, aggregate_retention_days=180),
        now=datetime(2026, 7, 10, tzinfo=UTC),
    )

    assert result.compacted_raw_rows == 5
    assert result.aggregate_rows == 5
    assert result.deleted_raw_rows == 5
    assert result.deleted_aggregate_rows == 0
    assert second.compacted_raw_rows == 0
    assert second.deleted_raw_rows == 0
    assert storage.count_rows("carry_quotes") == 1
    assert storage.count_rows("carry_funding_snapshots") == 1
    assert storage.count_rows("carry_basis_snapshots") == 1
    assert storage.count_rows("carry_positions") == 1
    assert storage.count_rows("carry_venue_health") == 1
    assert storage.count_rows("carry_decisions") == 2
    assert storage.count_rows("carry_daily_aggregates") == 5

    with sqlite3.connect(storage.path) as conn:
        metrics = conn.execute(
            """
            SELECT metrics_json
            FROM carry_daily_aggregates
            WHERE kind = 'funding' AND bucket_date = '2026-07-01'
            """
        ).fetchone()[0]
    assert "annualized_rate" in metrics


def test_carry_storage_retention_policy_rejects_unbounded_raw_window():
    try:
        CarryStorageRetentionPolicy(raw_retention_days=0)
    except ValueError as exc:
        assert "raw_retention_days" in str(exc)
    else:
        raise AssertionError("expected invalid raw retention policy to fail")


def _write_full_sample(storage: CarryStorage, *, timestamp: str, decision_id: str = "carry-001") -> None:
    storage.write_quote(
        CarryQuote(
            venue="hyperliquid",
            asset="BTC",
            spot_mid=100000.0,
            perp_mid=100100.0,
            oracle_mid=100050.0,
            mark_mid=100090.0,
            timestamp=timestamp,
            source_health="ok",
        )
    )
    storage.write_funding(
        FundingSnapshot(
            asset="BTC",
            venue="hyperliquid",
            hourly_rate=0.0001,
            annualized_rate=0.876,
            next_funding_time="2026-07-01T01:00:00Z",
            premium_index=0.001,
            timestamp=timestamp,
        )
    )
    storage.write_basis(
        BasisSnapshot(
            asset="BTC",
            spot_mid=100000.0,
            perp_mid=100100.0,
            basis_abs=100.0,
            basis_pct=0.001,
            annualized_basis=0.365,
            timestamp=timestamp,
        )
    )
    storage.write_decision(
        CarryDecision(
            decision_id=decision_id,
            mode="paper",
            action="open",
            reason="fixture",
            inputs={"asset": "BTC"},
            risk_checks=["paper_only"],
            expected_net_apr=0.18,
            exit_rule="net_apr_below_threshold",
            timestamp=timestamp,
        )
    )
    storage.write_position(
        CarryPosition(
            asset="BTC",
            spot_qty=0.01,
            perp_qty=-0.01,
            net_delta=0.0,
            entry_basis=0.001,
            accrued_funding=1.25,
            fees=0.35,
            margin_buffer=0.25,
            liquidation_distance=0.40,
        ),
        decision_id=decision_id,
        timestamp=timestamp,
    )
    storage.write_venue_health(venue="hyperliquid", status="ok", latency_ms=12.5, timestamp=timestamp)
