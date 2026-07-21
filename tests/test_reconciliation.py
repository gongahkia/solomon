from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from stonks_cli.reconciliation import (
    ReconciliationDifference,
    reconcile,
    reconcile_cash,
    reconcile_positions,
)
from stonks_cli.types import (
    Account,
    BrokerPositionSnapshot,
    Currency,
    EventKind,
    Instrument,
    LedgerEvent,
    SourceProvenance,
)


def test_reconciliation_reports_only_real_differences() -> None:
    differences = reconcile(
        {("main", Currency.USD): Decimal("10")},
        {("main", Currency.USD): Decimal("11")},
        {("main", "US:SPY"): Decimal("2")},
        {("main", "US:SPY"): Decimal("2")},
    )
    assert differences[0].subject == "cash:main:USD"
    assert differences[0].delta == Decimal("1")


def test_position_reconciliation_uses_latest_broker_snapshot() -> None:
    account = Account("moomoo", "123")
    instrument = Instrument("SPY", "US", Currency.USD)
    event = LedgerEvent(
        fingerprint="buy-1",
        source=SourceProvenance("moomoo", "a" * 64, "buy-1"),
        account=account,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        kind=EventKind.BUY,
        currency=Currency.USD,
        amount=Decimal("20"),
        quantity=Decimal("2"),
        instrument=instrument,
    )
    snapshots = [
        BrokerPositionSnapshot(
            source=SourceProvenance("moomoo", "b" * 64, "position-old"),
            account=account,
            instrument=instrument,
            quantity=Decimal("3"),
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        BrokerPositionSnapshot(
            source=SourceProvenance("moomoo", "c" * 64, "position-new"),
            account=account,
            instrument=instrument,
            quantity=Decimal("1"),
            observed_at=datetime(2026, 1, 2, tzinfo=UTC),
        ),
    ]

    differences = reconcile_positions([event], snapshots)
    assert differences == (ReconciliationDifference("position:moomoo:123:US:SPY", Decimal("2"), Decimal("1")),)


def test_cash_reconciliation_uses_canonical_ledger_cash() -> None:
    account = Account("moomoo", "123")
    event = LedgerEvent(
        fingerprint="deposit-1",
        source=SourceProvenance("moomoo", "a" * 64, "deposit-1"),
        account=account,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        kind=EventKind.CASH_DEPOSIT,
        currency=Currency.USD,
        amount=Decimal("100"),
    )

    differences = reconcile_cash([event], {(account.key, Currency.USD): Decimal("99")})
    assert differences == (ReconciliationDifference("cash:moomoo:123:USD", Decimal("100"), Decimal("99")),)
