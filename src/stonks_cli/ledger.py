from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from stonks_cli.errors import LedgerError
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
    decimal,
    utc,
)


def initialize(connection: sqlite3.Connection) -> None:
    columns = _columns(connection, "ledger_events")
    if not columns:
        _create_canonical_event_table(connection)
    elif "source_provider_id" not in columns:
        _migrate_legacy_event_table(connection)
    elif not _CANONICAL_EVENT_COLUMNS <= columns:
        raise LedgerError("unsupported ledger event schema")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ledger_events_time ON ledger_events(occurred_at, fingerprint)"
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ledger_events_source_record
        ON ledger_events(source_provider_id, source_hash, source_record_id)
        """
    )
    _initialize_position_snapshots(connection)


_CANONICAL_EVENT_COLUMNS = {
    "fingerprint",
    "source_provider_id",
    "source_hash",
    "source_record_id",
    "account_provider_id",
    "account_id",
    "account_name",
    "occurred_at",
    "kind",
    "lifecycle",
    "corrects_fingerprint",
    "currency",
    "amount",
    "quantity",
    "instrument_symbol",
    "instrument_market",
    "instrument_currency",
    "instrument_name",
    "fee",
    "metadata",
}


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def _create_canonical_event_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE ledger_events (
            fingerprint TEXT PRIMARY KEY,
            source_provider_id TEXT NOT NULL,
            source_hash TEXT NOT NULL CHECK(length(source_hash) = 64),
            source_record_id TEXT NOT NULL,
            account_provider_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            account_name TEXT,
            occurred_at TEXT NOT NULL,
            kind TEXT NOT NULL,
            lifecycle TEXT NOT NULL CHECK(lifecycle IN ('posted', 'correction', 'reversal')),
            corrects_fingerprint TEXT,
            currency TEXT NOT NULL,
            amount TEXT NOT NULL,
            quantity TEXT NOT NULL,
            instrument_symbol TEXT,
            instrument_market TEXT,
            instrument_currency TEXT,
            instrument_name TEXT,
            fee TEXT NOT NULL,
            metadata TEXT NOT NULL,
            CHECK(
                (lifecycle = 'posted' AND corrects_fingerprint IS NULL)
                OR (lifecycle IN ('correction', 'reversal') AND corrects_fingerprint IS NOT NULL)
            ),
            CHECK(corrects_fingerprint IS NULL OR corrects_fingerprint != fingerprint)
        )
        """
    )


def _initialize_position_snapshots(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_position_snapshots (
            source_provider_id TEXT NOT NULL,
            source_hash TEXT NOT NULL CHECK(length(source_hash) = 64),
            source_record_id TEXT NOT NULL,
            account_provider_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            account_name TEXT,
            instrument_symbol TEXT NOT NULL,
            instrument_market TEXT NOT NULL,
            instrument_currency TEXT NOT NULL,
            instrument_name TEXT,
            quantity TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            PRIMARY KEY(source_provider_id, source_hash, source_record_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS broker_position_snapshots_time
        ON broker_position_snapshots(observed_at, source_provider_id, source_hash, source_record_id)
        """
    )


def _migrate_legacy_event_table(connection: sqlite3.Connection) -> None:
    legacy_columns = _columns(connection, "ledger_events")
    if not {"fingerprint", "source_id", "account_id"} <= legacy_columns:
        raise LedgerError("unsupported ledger event schema")
    rows = connection.execute("SELECT * FROM ledger_events ORDER BY occurred_at, fingerprint").fetchall()
    connection.execute("ALTER TABLE ledger_events RENAME TO legacy_ledger_events")
    _create_canonical_event_table(connection)
    for row in rows:
        _insert_event(connection, _event_from_legacy_row(row))
    connection.execute("DROP TABLE legacy_ledger_events")


def append(ledger: EncryptedLedger, event: LedgerEvent) -> bool:
    inserted, _ = ingest_events(ledger, (event,))
    return inserted == 1


def ingest_events(ledger: EncryptedLedger, events: Iterable[LedgerEvent]) -> tuple[int, int]:
    events = tuple(events)
    inserted = skipped = 0
    with ledger.connection() as connection:
        initialize(connection)
        known_fingerprints = {
            row["fingerprint"] for row in connection.execute("SELECT fingerprint FROM ledger_events")
        }
        known_fingerprints.update(event.fingerprint for event in events)
        for event in events:
            if (
                event.lifecycle is not EventLifecycle.POSTED
                and event.corrects_fingerprint not in known_fingerprints
            ):
                raise LedgerError("correction target event was not imported")
        for event in events:
            if _insert_event(connection, event).rowcount == 1:
                inserted += 1
            else:
                skipped += 1
    return inserted, skipped


def _insert_event(connection: sqlite3.Connection, event: LedgerEvent) -> sqlite3.Cursor:
    instrument = event.instrument
    return connection.execute(
        """
        INSERT OR IGNORE INTO ledger_events (
            fingerprint, source_provider_id, source_hash, source_record_id, account_provider_id,
            account_id, account_name, occurred_at, kind, lifecycle, corrects_fingerprint, currency,
            amount, quantity, instrument_symbol, instrument_market, instrument_currency, instrument_name,
            fee, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.fingerprint,
            event.source.provider_id,
            event.source.source_hash,
            event.source.record_id,
            event.account.provider_id,
            event.account.account_id,
            event.account.name,
            event.occurred_at.isoformat(),
            event.kind.value,
            event.lifecycle.value,
            event.corrects_fingerprint,
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


def store_position_snapshot(ledger: EncryptedLedger, snapshot: BrokerPositionSnapshot) -> bool:
    with ledger.connection() as connection:
        initialize(connection)
        return _insert_position_snapshot(connection, snapshot).rowcount == 1


def _insert_position_snapshot(
    connection: sqlite3.Connection, snapshot: BrokerPositionSnapshot
) -> sqlite3.Cursor:
    return connection.execute(
        """
        INSERT OR IGNORE INTO broker_position_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot.source.provider_id,
            snapshot.source.source_hash,
            snapshot.source.record_id,
            snapshot.account.provider_id,
            snapshot.account.account_id,
            snapshot.account.name,
            snapshot.instrument.symbol,
            snapshot.instrument.market,
            snapshot.instrument.currency.value,
            snapshot.instrument.name,
            str(snapshot.quantity),
            snapshot.observed_at.isoformat(),
        ),
    )


def import_fingerprint(source: SourceProvenance, record: Mapping[str, Any]) -> str:
    payload = {
        "source": {
            "provider_id": source.provider_id,
            "source_hash": source.source_hash,
            "record_id": source.record_id,
        },
        "record": record,
    }
    try:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise LedgerError("import record must be JSON serializable") from error
    return hashlib.sha256(canonical.encode()).hexdigest()


def list_events(ledger: EncryptedLedger) -> list[LedgerEvent]:
    with ledger.connection() as connection:
        initialize(connection)
        rows = connection.execute(
            "SELECT * FROM ledger_events ORDER BY occurred_at, fingerprint"
        ).fetchall()
    return [_event_from_row(row) for row in rows]


def query_audit_trail(
    ledger: EncryptedLedger,
    *,
    account: Account | None = None,
    instrument: Instrument | None = None,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
) -> list[LedgerEvent]:
    clauses: list[str] = []
    parameters: list[str] = []
    if account is not None:
        clauses.extend(("account_provider_id = ?", "account_id = ?"))
        parameters.extend((account.provider_id, account.account_id))
    if instrument is not None:
        clauses.extend(("instrument_symbol = ?", "instrument_market = ?"))
        parameters.extend((instrument.symbol, instrument.market))
    start = None if from_at is None else utc(from_at)
    end = None if to_at is None else utc(to_at)
    if start is not None and end is not None and start > end:
        raise ValueError("audit query start must not be after end")
    if start is not None:
        clauses.append("occurred_at >= ?")
        parameters.append(start.isoformat())
    if end is not None:
        clauses.append("occurred_at <= ?")
        parameters.append(end.isoformat())
    query = "SELECT * FROM ledger_events"
    if clauses:
        query += f" WHERE {' AND '.join(clauses)}"
    query += " ORDER BY occurred_at, fingerprint"
    with ledger.connection() as connection:
        initialize(connection)
        rows = connection.execute(query, parameters).fetchall()
    return [_event_from_row(row) for row in rows]


def list_position_snapshots(ledger: EncryptedLedger) -> list[BrokerPositionSnapshot]:
    with ledger.connection() as connection:
        initialize(connection)
        rows = connection.execute(
            """
            SELECT * FROM broker_position_snapshots
            ORDER BY observed_at, source_provider_id, source_hash, source_record_id
            """
        ).fetchall()
    return [_position_snapshot_from_row(row) for row in rows]


def _position_snapshot_from_row(row: sqlite3.Row) -> BrokerPositionSnapshot:
    return BrokerPositionSnapshot(
        source=SourceProvenance(
            row["source_provider_id"], row["source_hash"], row["source_record_id"]
        ),
        account=Account(row["account_provider_id"], row["account_id"], row["account_name"]),
        instrument=Instrument(
            row["instrument_symbol"],
            row["instrument_market"],
            Currency(row["instrument_currency"]),
            row["instrument_name"],
        ),
        quantity=Decimal(row["quantity"]),
        observed_at=datetime.fromisoformat(row["observed_at"]),
    )


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
        source=SourceProvenance(
            row["source_provider_id"], row["source_hash"], row["source_record_id"]
        ),
        account=Account(row["account_provider_id"], row["account_id"], row["account_name"]),
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
        kind=EventKind(row["kind"]),
        lifecycle=EventLifecycle(row["lifecycle"]),
        corrects_fingerprint=row["corrects_fingerprint"],
        currency=Currency(row["currency"]),
        amount=Decimal(row["amount"]),
        quantity=Decimal(row["quantity"]),
        instrument=instrument,
        fee=Decimal(row["fee"]),
        metadata=json.loads(row["metadata"]),
    )


def _event_from_legacy_row(row: sqlite3.Row) -> LedgerEvent:
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


def effective_events(events: list[LedgerEvent]) -> tuple[LedgerEvent, ...]:
    corrected_fingerprints = {
        event.corrects_fingerprint
        for event in events
        if event.lifecycle is EventLifecycle.CORRECTION
    }
    return tuple(event for event in events if event.fingerprint not in corrected_fingerprints)


def cash_balances(events: list[LedgerEvent]) -> dict[tuple[str, Currency], Decimal]:
    balances: dict[tuple[str, Currency], Decimal] = defaultdict(Decimal)
    for event in effective_events(events):
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
    for event in sorted(effective_events(events), key=lambda item: (item.occurred_at, item.fingerprint)):
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
    return {key: quantity for key, quantity in values.items() if quantity != 0}


def import_csv(ledger: EncryptedLedger, path: Path) -> tuple[int, int, str]:
    content = path.read_bytes()
    source_hash = hashlib.sha256(content).hexdigest()
    try:
        rows = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    except UnicodeDecodeError as error:
        raise LedgerError("CSV must be UTF-8") from error
    if rows.fieldnames is None:
        raise LedgerError("CSV header is required")
    events = [
        event_from_csv_row(row, source_hash=source_hash, line=index)
        for index, row in enumerate(rows, start=2)
    ]
    ledger.archive_source(content)
    inserted, skipped = ingest_events(ledger, events)
    return inserted, skipped, source_hash


def event_from_csv_row(row: dict[str, str | None], *, source_hash: str, line: int) -> LedgerEvent:
    required = ("account_id", "occurred_at", "kind", "currency", "amount")
    missing = [name for name in required if not (row.get(name) or "").strip()]
    if missing:
        raise LedgerError(f"CSV row {line} missing:{','.join(missing)}")
    source = SourceProvenance("csv", source_hash, str(line))
    fingerprint = import_fingerprint(source, row)
    kind = EventKind((row["kind"] or "").strip().lower())
    try:
        lifecycle = EventLifecycle((row.get("lifecycle") or "posted").strip().lower())
    except ValueError as error:
        raise LedgerError(f"CSV row {line} invalid lifecycle") from error
    corrects_fingerprint = (row.get("corrects_fingerprint") or "").strip() or None
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
        source=source,
        account=Account("csv", (row["account_id"] or "").strip()),
        occurred_at=datetime.fromisoformat((row["occurred_at"] or "").strip()),
        kind=kind,
        lifecycle=lifecycle,
        corrects_fingerprint=corrects_fingerprint,
        currency=Currency((row["currency"] or "").upper()),
        amount=decimal(row["amount"] or "0"),
        quantity=decimal(row.get("quantity") or "0"),
        instrument=instrument,
        fee=decimal(row.get("fee") or "0"),
        metadata={"source_hash": source_hash, "line": line},
    )
