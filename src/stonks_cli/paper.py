from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from stonks_cli.errors import LedgerError
from stonks_cli.storage import EncryptedLedger
from stonks_cli.types import Currency, Instrument, decimal, utc


class PaperEventKind(StrEnum):
    DEPOSIT = "deposit"
    OPEN = "open"
    CLOSE = "close"


@dataclass(frozen=True)
class PaperEvent:
    event_id: str
    occurred_at: datetime
    kind: PaperEventKind
    currency: Currency
    amount: Decimal
    quantity: Decimal = Decimal("0")
    instrument: Instrument | None = None
    fee: Decimal = Decimal("0")
    model_id: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("paper event ID is required")
        object.__setattr__(self, "event_id", self.event_id.strip())
        object.__setattr__(self, "occurred_at", utc(self.occurred_at))
        object.__setattr__(self, "amount", decimal(self.amount))
        object.__setattr__(self, "quantity", decimal(self.quantity))
        object.__setattr__(self, "fee", decimal(self.fee))
        if self.amount <= 0 or self.quantity < 0 or self.fee < 0:
            raise ValueError("paper amounts must be positive and fees non-negative")
        if self.kind is PaperEventKind.DEPOSIT:
            if self.instrument is not None or self.quantity != 0 or self.fee != 0:
                raise ValueError("paper deposits cannot include an instrument, quantity, or fee")
        else:
            if self.instrument is None or self.quantity <= 0:
                raise ValueError("paper positions require an instrument and positive quantity")
            if self.instrument.currency is not self.currency:
                raise ValueError("paper instrument and event currencies must match")
        if self.model_id is not None:
            model_id = self.model_id.strip()
            object.__setattr__(self, "model_id", model_id or None)


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_events (
            event_id TEXT PRIMARY KEY,
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
            model_id TEXT
        )
        """
    )


def list_events(ledger: EncryptedLedger) -> tuple[PaperEvent, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute("SELECT * FROM paper_events ORDER BY occurred_at, event_id").fetchall()
    return tuple(_event_from_row(row) for row in rows)


def append(ledger: EncryptedLedger, event: PaperEvent) -> None:
    existing = list_events(ledger)
    if event.event_id in {item.event_id for item in existing}:
        raise LedgerError("paper event already exists")
    _validate_next_event(existing, event)
    with ledger.connection() as connection:
        _initialize(connection)
        connection.execute(
            "INSERT INTO paper_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.event_id,
                event.occurred_at.isoformat(),
                event.kind.value,
                event.currency.value,
                str(event.amount),
                str(event.quantity),
                None if event.instrument is None else event.instrument.symbol,
                None if event.instrument is None else event.instrument.market,
                None if event.instrument is None else event.instrument.currency.value,
                None if event.instrument is None else event.instrument.name,
                str(event.fee),
                event.model_id,
            ),
        )


def cash(events: tuple[PaperEvent, ...]) -> dict[Currency, Decimal]:
    balances: dict[Currency, Decimal] = defaultdict(Decimal)
    for event in events:
        if event.kind is PaperEventKind.DEPOSIT:
            balances[event.currency] += event.amount
        elif event.kind is PaperEventKind.OPEN:
            balances[event.currency] -= event.amount + event.fee
        else:
            balances[event.currency] += event.amount - event.fee
    return dict(balances)


def positions(events: tuple[PaperEvent, ...]) -> dict[str, Decimal]:
    values: dict[str, Decimal] = defaultdict(Decimal)
    for event in events:
        if event.instrument is None:
            continue
        if event.kind is PaperEventKind.OPEN:
            values[event.instrument.key] += event.quantity
        elif event.kind is PaperEventKind.CLOSE:
            values[event.instrument.key] -= event.quantity
    return {key: value for key, value in values.items() if value != 0}


def _validate_next_event(existing: tuple[PaperEvent, ...], event: PaperEvent) -> None:
    if event.kind is PaperEventKind.DEPOSIT:
        return
    if cash(existing).get(event.currency, Decimal("0")) < event.amount + event.fee and event.kind is PaperEventKind.OPEN:
        raise LedgerError("paper cash is insufficient")
    if event.kind is PaperEventKind.CLOSE:
        if event.instrument is None:
            raise LedgerError("paper position instrument is required")
        if positions(existing).get(event.instrument.key, Decimal("0")) < event.quantity:
            raise LedgerError("paper position is insufficient")


def _event_from_row(row: sqlite3.Row) -> PaperEvent:
    instrument = None
    if row["instrument_symbol"] is not None:
        instrument = Instrument(
            row["instrument_symbol"],
            row["instrument_market"],
            Currency(row["instrument_currency"]),
            row["instrument_name"],
        )
    return PaperEvent(
        row["event_id"],
        datetime.fromisoformat(row["occurred_at"]).astimezone(UTC),
        PaperEventKind(row["kind"]),
        Currency(row["currency"]),
        Decimal(row["amount"]),
        Decimal(row["quantity"]),
        instrument,
        Decimal(row["fee"]),
        row["model_id"],
    )
