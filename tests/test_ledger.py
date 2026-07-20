from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from stonks_cli.accounting import fifo_lots
from stonks_cli.config import ProfileConfig
from stonks_cli.ledger import append, cash_balances, import_csv, list_events, positions
from stonks_cli.storage import EncryptedLedger, generate_key_file
from stonks_cli.types import Currency, EventKind, Instrument, LedgerEvent


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
        source_id=kind.value,
        account_id="main",
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


def test_cash_and_positions_follow_trade_events(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    append(ledger, _event(EventKind.CASH_DEPOSIT, amount="100"))
    append(ledger, _event(EventKind.BUY, quantity="2", amount="20"))
    events = list_events(ledger)
    assert cash_balances(events)[("main", Currency.USD)] == Decimal("79")
    assert positions(events)[("main", "US:SPY")] == Decimal("2")


def test_csv_import_archives_and_deduplicates(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    source = tmp_path / "events.csv"
    source.write_text(
        "account_id,occurred_at,kind,currency,amount,quantity,symbol,market,fee\n"
        "main,2026-01-01T00:00:00+00:00,cash_deposit,USD,100,,,,0\n"
    )
    assert import_csv(ledger, source)[:2] == (1, 0)
    assert import_csv(ledger, source)[:2] == (0, 1)


def test_fifo_lots_calculates_realized_profit(tmp_path: Path, monkeypatch) -> None:
    ledger = _ledger(tmp_path, monkeypatch)
    append(ledger, _event(EventKind.BUY, quantity="2", amount="20"))
    sell = _event(EventKind.SELL, quantity="1", amount="20")
    append(ledger, sell)
    lots, realized = fifo_lots(list_events(ledger))
    assert lots[0].quantity == Decimal("1")
    assert realized[0].value == Decimal("8.5")
