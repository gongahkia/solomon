from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from stonks_cli.errors import LedgerError
from stonks_cli.storage import EncryptedLedger
from stonks_cli.types import (
    Account,
    Currency,
    EventKind,
    Instrument,
    LedgerEvent,
    SourceProvenance,
    decimal,
)


def initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_events (
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
        "CREATE INDEX IF NOT EXISTS ledger_events_time ON ledger_events(occurred_at, fingerprint)"
    )


def append(ledger: EncryptedLedger, event: LedgerEvent) -> bool:
    with ledger.connection() as connection:
        initialize(connection)
        instrument = event.instrument
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO ledger_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.fingerprint,
                event.source_id,
                event.account_id,
                event.occurred_at.isoformat(),
                event.kind.value,
                event.currency.value,
                str(event.amount),
                str(event.quantity),
                None if instrument is None else instrument.symbol,
                None if instrument is None else instrument.market,
                None if instrument is None else instrument.currency.value,
                None if instrument is None else instrument.name,
                str(event.fee),
                json.dumps(event.metadata, sort_keys=True, separators=(",", ":")),
            ),
        )
        return cursor.rowcount == 1


def list_events(ledger: EncryptedLedger) -> list[LedgerEvent]:
    with ledger.connection() as connection:
        initialize(connection)
        rows = connection.execute(
            "SELECT * FROM ledger_events ORDER BY occurred_at, fingerprint"
        ).fetchall()
    return [_event_from_row(row) for row in rows]


def _event_from_row(row: sqlite3.Row) -> LedgerEvent:
    instrument = None
    if row["instrument_symbol"] is not None:
        instrument = Instrument(
            row["instrument_symbol"],
            row["instrument_market"],
            Currency(row["instrument_currency"]),
            row["instrument_name"],
        )
    return LedgerEvent(
        fingerprint=row["fingerprint"],
        source=_source_from_key(row["source_id"]),
        account=_account_from_key(row["account_id"]),
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
        kind=EventKind(row["kind"]),
        currency=Currency(row["currency"]),
        amount=Decimal(row["amount"]),
        quantity=Decimal(row["quantity"]),
        instrument=instrument,
        fee=Decimal(row["fee"]),
        metadata=json.loads(row["metadata"]),
    )


def _account_from_key(value: str) -> Account:
    provider_id, separator, account_id = value.partition(":")
    if separator:
        return Account(provider_id, account_id)
    return Account("legacy", value)


def _source_from_key(value: str) -> SourceProvenance:
    parts = value.split(":", maxsplit=2)
    if len(parts) == 3:
        return SourceProvenance(*parts)
    if len(parts) == 2:
        return SourceProvenance("legacy", *parts)
    return SourceProvenance("legacy", hashlib.sha256(value.encode()).hexdigest(), value)


def cash_balances(events: list[LedgerEvent]) -> dict[tuple[str, Currency], Decimal]:
    balances: dict[tuple[str, Currency], Decimal] = defaultdict(Decimal)
    for event in events:
        delta = Decimal("0")
        if event.kind in {EventKind.CASH_DEPOSIT, EventKind.DIVIDEND}:
            delta = event.amount
        elif event.kind in {EventKind.CASH_WITHDRAWAL, EventKind.FEE}:
            delta = -event.amount
        elif event.kind is EventKind.BUY:
            delta = -event.amount - event.fee
        elif event.kind is EventKind.SELL:
            delta = event.amount - event.fee
        balances[(event.account_id, event.currency)] += delta
    return dict(balances)


def positions(events: list[LedgerEvent]) -> dict[tuple[str, str], Decimal]:
    values: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for event in events:
        if event.instrument is None:
            continue
        key = (event.account_id, event.instrument.key)
        if event.kind is EventKind.BUY:
            values[key] += event.quantity
        elif event.kind is EventKind.SELL:
            values[key] -= event.quantity
        elif event.kind is EventKind.SPLIT:
            values[key] *= event.quantity
        if values[key] < 0:
            raise LedgerError(f"negative position:{event.account_id}:{event.instrument.key}")
    return dict(values)


def import_csv(ledger: EncryptedLedger, path: Path) -> tuple[int, int, str]:
    content = path.read_bytes()
    source_hash = ledger.archive_source(content)
    try:
        rows = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    except UnicodeDecodeError as error:
        raise LedgerError("CSV must be UTF-8") from error
    if rows.fieldnames is None:
        raise LedgerError("CSV header is required")
    inserted = skipped = 0
    for index, row in enumerate(rows, start=2):
        event = event_from_csv_row(row, source_hash=source_hash, line=index)
        if append(ledger, event):
            inserted += 1
        else:
            skipped += 1
    return inserted, skipped, source_hash


def event_from_csv_row(row: dict[str, str | None], *, source_hash: str, line: int) -> LedgerEvent:
    required = ("account_id", "occurred_at", "kind", "currency", "amount")
    missing = [name for name in required if not (row.get(name) or "").strip()]
    if missing:
        raise LedgerError(f"CSV row {line} missing:{','.join(missing)}")
    raw = json.dumps(row, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(f"{source_hash}:{line}:{raw}".encode()).hexdigest()
    kind = EventKind((row["kind"] or "").strip().lower())
    symbol = (row.get("symbol") or "").strip()
    market = (row.get("market") or "").strip()
    instrument = None
    if symbol or market:
        if not symbol or not market:
            raise LedgerError(f"CSV row {line} requires both symbol and market")
        instrument = Instrument(
            symbol,
            market,
            Currency((row.get("instrument_currency") or row["currency"] or "").upper()),
        )
    return LedgerEvent(
        fingerprint=fingerprint,
        source=SourceProvenance("csv", source_hash, str(line)),
        account=Account("csv", (row["account_id"] or "").strip()),
        occurred_at=datetime.fromisoformat((row["occurred_at"] or "").strip()),
        kind=kind,
        currency=Currency((row["currency"] or "").upper()),
        amount=decimal(row["amount"] or "0"),
        quantity=decimal(row.get("quantity") or "0"),
        instrument=instrument,
        fee=decimal(row.get("fee") or "0"),
        metadata={"source_hash": source_hash, "line": line},
    )
