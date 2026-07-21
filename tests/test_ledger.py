from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from stonks_cli.accounting import fifo_lots
from stonks_cli.config import ProfileConfig
from stonks_cli.errors import LedgerError
from stonks_cli.ledger import (
    append,
    cash_balances,
    import_csv,
    import_fingerprint,
    ingest_events,
    list_events,
    positions,
)
from stonks_cli.storage import EncryptedLedger, generate_key_file
from stonks_cli.types import (
    Account,
    Currency,
    EventKind,
    EventLifecycle,
    Instrument,
    LedgerEvent,
    SourceProvenance,
)


def _ledger(tmp_path: Path, monkeypatch) -> EncryptedLedger:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    key = tmp_path / "key"
    generate_key_file(key)
    return EncryptedLedger(ProfileConfig("personal", str(key)))


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


def test_csv_import_archives_and_deduplicates(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    source = tmp_path / "events.csv"
    source.write_text(
        "account_id,occurred_at,kind,currency,amount,quantity,symbol,market,fee\n"
        "main,2026-01-01T00:00:00+00:00,cash_deposit,USD,100,,,,0\n"
    )
    assert import_csv(ledger, source)[:2] == (1, 0)
    assert import_csv(ledger, source)[:2] == (0, 1)


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
