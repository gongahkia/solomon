from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from conftest import encrypted_ledger

from stonks_cli.errors import LedgerError
from stonks_cli.paper import PaperEvent, PaperEventKind, append, cash, list_events, positions
from stonks_cli.types import Currency, Instrument


def _event(event_id: str, kind: PaperEventKind, amount: str, quantity: str = "0") -> PaperEvent:
    return PaperEvent(
        event_id,
        datetime(2026, 1, 1, tzinfo=UTC),
        kind,
        Currency.USD,
        Decimal(amount),
        Decimal(quantity),
        None if kind is PaperEventKind.DEPOSIT else Instrument("SPY", "US", Currency.USD),
    )


def test_paper_portfolio_tracks_cash_and_positions(tmp_path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    append(ledger, _event("deposit", PaperEventKind.DEPOSIT, "1000"))
    append(ledger, _event("open", PaperEventKind.OPEN, "400", "4"))
    append(ledger, _event("close", PaperEventKind.CLOSE, "500", "4"))

    events = list_events(ledger)

    assert cash(events) == {Currency.USD: Decimal("1100")}
    assert positions(events) == {}


def test_paper_portfolio_rejects_unfunded_or_unheld_positions(tmp_path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)

    with pytest.raises(LedgerError, match="cash"):
        append(ledger, _event("open", PaperEventKind.OPEN, "100", "1"))
    append(ledger, _event("deposit", PaperEventKind.DEPOSIT, "100"))
    with pytest.raises(LedgerError, match="position"):
        append(ledger, _event("close", PaperEventKind.CLOSE, "100", "1"))
