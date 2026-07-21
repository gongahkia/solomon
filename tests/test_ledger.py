from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import encrypted_ledger

from stonks_cli.accounting import fifo_lots
from stonks_cli.errors import LedgerError
from stonks_cli.ledger import (
    append,
    cash_balances,
    effective_events,
    event_from_csv_row,
    import_csv,
    import_fingerprint,
    ingest_events,
    integrity_errors,
    list_events,
    list_position_snapshots,
    positions,
    query_audit_trail,
    store_position_snapshot,
)
from stonks_cli.storage import EncryptedLedger
from stonks_cli.types import (
    Account,
    BrokerPositionSnapshot,
    Currency,
    EventKind,
    EventLifecycle,
    Instrument,
    LedgerEvent,
    SourceProvenance,
)


def _ledger(tmp_path: Path, monkeypatch) -> EncryptedLedger:
    return encrypted_ledger(tmp_path, monkeypatch)


def _event(kind: EventKind, *, quantity: str = "0", amount: str = "0") -> LedgerEvent:
    instrument = (
        Instrument("SPY", "US", Currency.USD) if kind in {EventKind.BUY, EventKind.SELL} else None
    )
    return LedgerEvent(
        fingerprint=kind.value,
        source=SourceProvenance("test", "0" * 64, kind.value),
        account=Account("test", "main"),
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        kind=kind,
        currency=Currency.USD,
        amount=Decimal(amount),
        quantity=Decimal(quantity),
        instrument=instrument,
        fee=Decimal("1") if kind in {EventKind.BUY, EventKind.SELL} else Decimal("0"),
    )


def test_events_are_idempotent_and_encrypted(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    event = _event(EventKind.CASH_DEPOSIT, amount="100")
    assert append(ledger, event) is True
    assert append(ledger, event) is False
    assert list_events(ledger) == [event]
    assert b"cash_deposit" not in ledger.path.read_bytes()


def test_broker_position_snapshots_are_idempotent_and_encrypted(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    snapshot = BrokerPositionSnapshot(
        source=SourceProvenance("moomoo", "a" * 64, "position-1"),
        account=Account("moomoo", "123", "Personal"),
        instrument=Instrument("SPY", "US", Currency.USD),
        quantity=Decimal("2"),
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert store_position_snapshot(ledger, snapshot) is True
    assert store_position_snapshot(ledger, snapshot) is False
    assert list_position_snapshots(ledger) == [snapshot]
    assert b"position-1" not in ledger.path.read_bytes()


def test_audit_trail_queries_immutable_events_by_identity_and_time(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    deposit = _event(EventKind.CASH_DEPOSIT, amount="100")
    buy = LedgerEvent(
        fingerprint="audit-buy",
        source=SourceProvenance("test", "0" * 64, "audit-buy"),
        account=deposit.account,
        occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
        kind=EventKind.BUY,
        currency=Currency.USD,
        amount=Decimal("20"),
        quantity=Decimal("2"),
        instrument=Instrument("SPY", "US", Currency.USD),
    )
    assert append(ledger, deposit) is True
    assert append(ledger, buy) is True

    assert query_audit_trail(ledger, account=deposit.account) == [deposit, buy]
    assert query_audit_trail(ledger, instrument=buy.instrument) == [buy]
    assert query_audit_trail(ledger, from_at=datetime(2026, 1, 2, tzinfo=UTC)) == [buy]
    with pytest.raises(ValueError, match="start"):
        query_audit_trail(
            ledger,
            from_at=datetime(2026, 1, 3, tzinfo=UTC),
            to_at=datetime(2026, 1, 2, tzinfo=UTC),
        )


def test_canonical_event_schema_round_trips_lifecycle_and_identities(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    posted = _event(EventKind.CASH_DEPOSIT, amount="100")
    correction = LedgerEvent(
        fingerprint="corrected-deposit",
        source=SourceProvenance("csv", "0" * 64, "corrected-deposit"),
        account=Account("test", "main", "Personal"),
        occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
        kind=EventKind.CASH_DEPOSIT,
        currency=Currency.USD,
        amount=Decimal("125"),
        lifecycle=EventLifecycle.CORRECTION,
        corrects_fingerprint=posted.fingerprint,
    )
    assert append(ledger, posted) is True
    assert append(ledger, correction) is True

    with ledger.connection() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(ledger_events)")}
        assert {"source_provider_id", "source_hash", "account_provider_id", "lifecycle"} <= columns
        assert "source_id" not in columns

    assert list_events(ledger) == [posted, correction]


def test_import_fingerprint_is_canonical_and_source_specific() -> None:
    source = SourceProvenance("csv", "a" * 64, "2")
    record = {"amount": "100", "kind": "cash_deposit"}

    assert import_fingerprint(source, record) == "aa86d4ac08452c7cd6d45d4b9083785e312372a73ad45ab9c6d07ba0fea608fa"
    assert import_fingerprint(source, record) == import_fingerprint(
        source, {"kind": "cash_deposit", "amount": "100"}
    )
    assert import_fingerprint(source, record) != import_fingerprint(
        SourceProvenance("csv", "a" * 64, "3"), record
    )


def test_cash_and_positions_follow_trade_events(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    append(ledger, _event(EventKind.CASH_DEPOSIT, amount="100"))
    append(ledger, _event(EventKind.BUY, quantity="2", amount="20"))
    events = list_events(ledger)
    assert cash_balances(events)[("test:main", Currency.USD)] == Decimal("79")
    assert positions(events)[("test:main", "US:SPY")] == Decimal("2")


def test_cash_balances_apply_corrections_and_compensating_reversals() -> None:
    original = _event(EventKind.CASH_DEPOSIT, amount="100")
    correction = LedgerEvent(
        fingerprint="corrected-deposit",
        source=SourceProvenance("test", "0" * 64, "corrected-deposit"),
        account=original.account,
        occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
        kind=EventKind.CASH_DEPOSIT,
        currency=Currency.USD,
        amount=Decimal("125"),
        lifecycle=EventLifecycle.CORRECTION,
        corrects_fingerprint=original.fingerprint,
    )
    reversal = LedgerEvent(
        fingerprint="reversed-deposit",
        source=SourceProvenance("test", "0" * 64, "reversed-deposit"),
        account=original.account,
        occurred_at=datetime(2026, 1, 3, tzinfo=UTC),
        kind=EventKind.CASH_WITHDRAWAL,
        currency=Currency.USD,
        amount=Decimal("125"),
        lifecycle=EventLifecycle.REVERSAL,
        corrects_fingerprint=correction.fingerprint,
    )

    assert effective_events([original, correction, reversal]) == (correction, reversal)
    assert cash_balances([original, correction, reversal]) == {("test:main", Currency.USD): Decimal("0")}


def test_positions_apply_corrections_reversals_and_event_order() -> None:
    original = _event(EventKind.BUY, quantity="2", amount="20")
    correction = LedgerEvent(
        fingerprint="corrected-buy",
        source=SourceProvenance("test", "0" * 64, "corrected-buy"),
        account=original.account,
        occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
        kind=EventKind.BUY,
        currency=Currency.USD,
        amount=Decimal("30"),
        quantity=Decimal("3"),
        instrument=original.instrument,
        lifecycle=EventLifecycle.CORRECTION,
        corrects_fingerprint=original.fingerprint,
    )
    reversal = LedgerEvent(
        fingerprint="reversed-buy",
        source=SourceProvenance("test", "0" * 64, "reversed-buy"),
        account=original.account,
        occurred_at=datetime(2026, 1, 3, tzinfo=UTC),
        kind=EventKind.SELL,
        currency=Currency.USD,
        amount=Decimal("30"),
        quantity=Decimal("3"),
        instrument=original.instrument,
        lifecycle=EventLifecycle.REVERSAL,
        corrects_fingerprint=correction.fingerprint,
    )

    assert positions([reversal, correction, original]) == {}


def test_ledger_integrity_checks_relational_and_position_invariants() -> None:
    original = _event(EventKind.BUY, quantity="2", amount="20")
    missing_target = LedgerEvent(
        fingerprint="missing-target",
        source=SourceProvenance("test", "0" * 64, "missing-target"),
        account=original.account,
        occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
        kind=EventKind.BUY,
        currency=Currency.USD,
        amount=Decimal("20"),
        quantity=Decimal("2"),
        instrument=original.instrument,
        lifecycle=EventLifecycle.CORRECTION,
        corrects_fingerprint="not-imported",
    )
    cycle_a = LedgerEvent(
        fingerprint="cycle-a",
        source=SourceProvenance("test", "0" * 64, "cycle-a"),
        account=original.account,
        occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
        kind=EventKind.BUY,
        currency=Currency.USD,
        amount=Decimal("20"),
        quantity=Decimal("2"),
        instrument=original.instrument,
        lifecycle=EventLifecycle.CORRECTION,
        corrects_fingerprint="cycle-b",
    )
    cycle_b = LedgerEvent(
        fingerprint="cycle-b",
        source=SourceProvenance("test", "0" * 64, "cycle-b"),
        account=original.account,
        occurred_at=datetime(2026, 1, 3, tzinfo=UTC),
        kind=EventKind.BUY,
        currency=Currency.USD,
        amount=Decimal("20"),
        quantity=Decimal("2"),
        instrument=original.instrument,
        lifecycle=EventLifecycle.CORRECTION,
        corrects_fingerprint="cycle-a",
    )
    oversell = LedgerEvent(
        fingerprint="oversell",
        source=SourceProvenance("test", "0" * 64, "oversell"),
        account=original.account,
        occurred_at=datetime(2026, 1, 4, tzinfo=UTC),
        kind=EventKind.SELL,
        currency=Currency.USD,
        amount=Decimal("50"),
        quantity=Decimal("5"),
        instrument=original.instrument,
    )

    assert integrity_errors([original]) == ()
    assert integrity_errors([missing_target]) == ("missing lifecycle target:not-imported",)
    assert integrity_errors([cycle_a, cycle_b]) == ("correction cycle:cycle-a,cycle-b",)
    assert integrity_errors([oversell]) == ("negative position:test:main:US:SPY",)


def test_csv_import_archives_and_deduplicates(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    source = tmp_path / "events.csv"
    source.write_text(
        "account_id,occurred_at,kind,currency,amount,quantity,symbol,market,fee\n"
        "main,2026-01-01T00:00:00+00:00,cash_deposit,USD,100,,,,0\n"
    )
    assert import_csv(ledger, source)[:2] == (1, 0)
    assert import_csv(ledger, source)[:2] == (0, 1)


def test_csv_imports_cash_deposits_and_withdrawals(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    source = tmp_path / "transfers.csv"
    source.write_text(
        "account_id,occurred_at,kind,currency,amount\n"
        "main,2026-01-01T00:00:00+00:00,cash_deposit,USD,100\n"
        "main,2026-01-02T00:00:00+00:00,cash_withdrawal,USD,25\n"
    )

    assert import_csv(ledger, source)[:2] == (2, 0)
    events = list_events(ledger)
    assert [event.kind for event in events] == [EventKind.CASH_DEPOSIT, EventKind.CASH_WITHDRAWAL]
    assert cash_balances(events)[("csv:main", Currency.USD)] == Decimal("75")


def test_csv_imports_buy_and_sell_fills(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    source = tmp_path / "fills.csv"
    source.write_text(
        "account_id,occurred_at,kind,currency,amount,quantity,symbol,market,fee\n"
        "main,2026-01-01T00:00:00+00:00,cash_deposit,USD,100,,,,0\n"
        "main,2026-01-02T00:00:00+00:00,buy,USD,20,2,SPY,US,1\n"
        "main,2026-01-03T00:00:00+00:00,sell,USD,15,1,SPY,US,1\n"
    )

    assert import_csv(ledger, source)[:2] == (3, 0)
    events = list_events(ledger)
    assert [event.kind for event in events] == [
        EventKind.CASH_DEPOSIT,
        EventKind.BUY,
        EventKind.SELL,
    ]
    assert cash_balances(events)[("csv:main", Currency.USD)] == Decimal("93")
    assert positions(events)[("csv:main", "US:SPY")] == Decimal("1")


def test_csv_imports_fee_events(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    source = tmp_path / "fees.csv"
    source.write_text(
        "account_id,occurred_at,kind,currency,amount\n"
        "main,2026-01-01T00:00:00+00:00,cash_deposit,USD,100\n"
        "main,2026-01-02T00:00:00+00:00,fee,USD,5\n"
    )

    assert import_csv(ledger, source)[:2] == (2, 0)
    events = list_events(ledger)
    assert events[1].kind is EventKind.FEE
    assert cash_balances(events)[("csv:main", Currency.USD)] == Decimal("95")


def test_csv_imports_dividend_events(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    source = tmp_path / "dividends.csv"
    source.write_text(
        "account_id,occurred_at,kind,currency,amount,symbol,market\n"
        "main,2026-01-01T00:00:00+00:00,cash_deposit,USD,100,,\n"
        "main,2026-01-02T00:00:00+00:00,dividend,USD,3,SPY,US\n"
    )

    assert import_csv(ledger, source)[:2] == (2, 0)
    events = list_events(ledger)
    assert events[1].kind is EventKind.DIVIDEND
    assert events[1].instrument == Instrument("SPY", "US", Currency.USD)
    assert cash_balances(events)[("csv:main", Currency.USD)] == Decimal("103")


def test_csv_imports_split_events_without_cash_effect(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    source = tmp_path / "splits.csv"
    source.write_text(
        "account_id,occurred_at,kind,currency,amount,quantity,symbol,market,fee\n"
        "main,2026-01-01T00:00:00+00:00,cash_deposit,USD,100,,,,0\n"
        "main,2026-01-02T00:00:00+00:00,buy,USD,20,2,SPY,US,0\n"
        "main,2026-01-03T00:00:00+00:00,split,USD,0,2,SPY,US,0\n"
    )

    assert import_csv(ledger, source)[:2] == (3, 0)
    events = list_events(ledger)
    assert events[2].kind is EventKind.SPLIT
    assert positions(events)[("csv:main", "US:SPY")] == Decimal("4")
    assert cash_balances(events)[("csv:main", Currency.USD)] == Decimal("80")


def test_csv_import_does_not_archive_or_persist_a_partial_file(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    source = tmp_path / "events.csv"
    source.write_text(
        "account_id,occurred_at,kind,currency,amount,quantity,symbol,market,fee\n"
        "main,2026-01-01T00:00:00+00:00,cash_deposit,USD,100,,,,0\n"
        "main,2026-01-02T00:00:00+00:00,,USD,100,,,,0\n"
    )

    with pytest.raises(LedgerError, match="missing:kind"):
        import_csv(ledger, source)

    assert list_events(ledger) == []
    assert not ledger.sources.exists()


def test_ingest_events_rolls_back_on_a_late_storage_failure(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    valid = _event(EventKind.CASH_DEPOSIT, amount="100")
    invalid = LedgerEvent(
        fingerprint="invalid",
        source=SourceProvenance("test", "0" * 64, "invalid"),
        account=Account("test", "main"),
        occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
        kind=EventKind.CASH_DEPOSIT,
        currency=Currency.USD,
        amount=Decimal("100"),
        metadata={"not_json": object()},
    )

    with pytest.raises(TypeError, match="JSON serializable"):
        ingest_events(ledger, (valid, invalid))
    assert list_events(ledger) == []


def test_ingest_events_skips_conflicting_source_records(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    event = _event(EventKind.CASH_DEPOSIT, amount="100")
    conflicting = LedgerEvent(
        fingerprint="conflicting-source-record",
        source=event.source,
        account=event.account,
        occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
        kind=EventKind.CASH_DEPOSIT,
        currency=Currency.USD,
        amount=Decimal("200"),
    )

    assert ingest_events(ledger, (event, conflicting)) == (1, 1)
    assert list_events(ledger) == [event]


def test_csv_correction_and_reversal_rows_reference_prior_events(tmp_path: Path, monkeypatch) -> None:
    original = event_from_csv_row(
        {
            "account_id": "main",
            "occurred_at": "2026-01-01T00:00:00+00:00",
            "kind": "cash_deposit",
            "currency": "USD",
            "amount": "100",
        },
        source_hash="a" * 64,
        line=2,
    )
    correction = event_from_csv_row(
        {
            "account_id": "main",
            "occurred_at": "2026-01-02T00:00:00+00:00",
            "kind": "cash_deposit",
            "currency": "USD",
            "amount": "125",
            "lifecycle": "correction",
            "corrects_fingerprint": original.fingerprint,
        },
        source_hash="b" * 64,
        line=2,
    )
    reversal = event_from_csv_row(
        {
            "account_id": "main",
            "occurred_at": "2026-01-03T00:00:00+00:00",
            "kind": "cash_withdrawal",
            "currency": "USD",
            "amount": "125",
            "lifecycle": "reversal",
            "corrects_fingerprint": correction.fingerprint,
        },
        source_hash="c" * 64,
        line=2,
    )

    assert correction.lifecycle is EventLifecycle.CORRECTION
    assert correction.corrects_fingerprint == original.fingerprint
    assert reversal.lifecycle is EventLifecycle.REVERSAL
    assert reversal.corrects_fingerprint == correction.fingerprint
    ledger = _ledger(tmp_path, monkeypatch)
    assert ingest_events(ledger, (original, correction, reversal)) == (3, 0)
    assert list_events(ledger) == [original, correction, reversal]


def test_ingest_events_rejects_corrections_without_the_target(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    correction = LedgerEvent(
        fingerprint="missing-target-correction",
        source=SourceProvenance("test", "0" * 64, "missing-target-correction"),
        account=Account("test", "main"),
        occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
        kind=EventKind.CASH_DEPOSIT,
        currency=Currency.USD,
        amount=Decimal("100"),
        lifecycle=EventLifecycle.CORRECTION,
        corrects_fingerprint="missing",
    )

    with pytest.raises(LedgerError, match="target event"):
        ingest_events(ledger, (correction,))
    assert list_events(ledger) == []


def test_legacy_persisted_event_ids_are_read_as_canonical_identities(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    source_hash = "a" * 64
    with ledger.connection() as connection:
        connection.execute(
            """
            CREATE TABLE ledger_events (
                fingerprint TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                kind TEXT NOT NULL,
                currency TEXT NOT NULL,
                amount TEXT NOT NULL,
                quantity TEXT NOT NULL,
                instrument_symbol TEXT,
                instrument_market TEXT,
                instrument_currency TEXT,
                instrument_name TEXT,
                fee TEXT NOT NULL,
                metadata TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO ledger_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "event-1",
                f"{source_hash}:2",
                "main",
                "2026-01-01T00:00:00+00:00",
                "cash_deposit",
                "USD",
                "100",
                "0",
                None,
                None,
                None,
                None,
                "0",
                "{}",
            ),
        )

    event = list_events(ledger)[0]
    assert event.source == SourceProvenance("legacy", source_hash, "2")
    assert event.account == Account("legacy", "main")
    with ledger.connection() as connection:
        assert "source_id" not in {row["name"] for row in connection.execute("PRAGMA table_info(ledger_events)")}


def test_fifo_lots_calculates_realized_profit(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    append(ledger, _event(EventKind.BUY, quantity="2", amount="20"))
    sell = _event(EventKind.SELL, quantity="1", amount="20")
    append(ledger, sell)
    lots, realized = fifo_lots(list_events(ledger))
    assert lots[0].quantity == Decimal("1")
    assert realized[0].value == Decimal("8.5")
