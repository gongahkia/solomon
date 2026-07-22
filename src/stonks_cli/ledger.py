from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from stonks_cli.errors import LedgerError
from stonks_cli.storage import EncryptedLedger
from stonks_cli.types import (
    Account,
    BrokerCashFlow,
    BrokerCashSnapshot,
    BrokerDividendDeclaration,
    BrokerFeeRecord,
    BrokerPositionSnapshot,
    Currency,
    DividendCreditMapping,
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
    _initialize_cash_snapshots(connection)
    _initialize_cash_flows(connection)
    _initialize_dividend_declarations(connection)
    _initialize_dividend_credit_mappings(connection)
    _initialize_fee_records(connection)


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


def _initialize_cash_snapshots(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_cash_snapshots (
            source_provider_id TEXT NOT NULL,
            source_hash TEXT NOT NULL CHECK(length(source_hash) = 64),
            source_record_id TEXT NOT NULL,
            account_provider_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            account_name TEXT,
            currency TEXT NOT NULL,
            amount TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            PRIMARY KEY(source_provider_id, source_hash, source_record_id)
        )
        """
    )


def _initialize_cash_flows(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_cash_flows (
            source_provider_id TEXT NOT NULL,
            source_hash TEXT NOT NULL CHECK(length(source_hash) = 64),
            source_record_id TEXT NOT NULL,
            account_provider_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            account_name TEXT,
            clearing_date TEXT NOT NULL,
            settlement_date TEXT NOT NULL,
            currency TEXT NOT NULL,
            flow_type TEXT NOT NULL,
            direction TEXT NOT NULL,
            amount TEXT NOT NULL,
            remark TEXT,
            PRIMARY KEY(source_provider_id, source_hash, source_record_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS broker_cash_snapshots_time
        ON broker_cash_snapshots(observed_at, source_provider_id, source_hash, source_record_id)
        """
    )


def _initialize_fee_records(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_fee_records (
            source_provider_id TEXT NOT NULL,
            source_hash TEXT NOT NULL CHECK(length(source_hash) = 64),
            source_record_id TEXT NOT NULL,
            raw_source_hash TEXT NOT NULL CHECK(length(raw_source_hash) = 64),
            account_provider_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            account_name TEXT,
            currency TEXT NOT NULL,
            amount TEXT NOT NULL,
            classification TEXT NOT NULL,
            transaction_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            PRIMARY KEY(source_provider_id, source_hash, source_record_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS broker_fee_records_time
        ON broker_fee_records(occurred_at, source_provider_id, source_hash, source_record_id)
        """
    )


def _initialize_dividend_declarations(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_dividend_declarations (
            source_provider_id TEXT NOT NULL,
            source_hash TEXT NOT NULL CHECK(length(source_hash) = 64),
            source_record_id TEXT NOT NULL,
            raw_source_hash TEXT NOT NULL CHECK(length(raw_source_hash) = 64),
            account_provider_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            account_name TEXT,
            instrument_symbol TEXT NOT NULL,
            instrument_market TEXT NOT NULL,
            instrument_currency TEXT NOT NULL,
            instrument_name TEXT,
            announced_at TEXT,
            status TEXT,
            record_date TEXT,
            ex_date TEXT,
            payable_date TEXT,
            statement TEXT,
            amount_per_share TEXT,
            currency TEXT,
            PRIMARY KEY(source_provider_id, source_hash, source_record_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS broker_dividend_declarations_account
        ON broker_dividend_declarations(account_provider_id, account_id, record_date)
        """
    )


def _initialize_dividend_credit_mappings(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dividend_credit_mappings (
            declaration_source_key TEXT PRIMARY KEY,
            cash_flow_source_key TEXT NOT NULL UNIQUE,
            cash_snapshot_source_key TEXT NOT NULL,
            event_fingerprint TEXT NOT NULL UNIQUE,
            gross_currency TEXT NOT NULL,
            gross_amount TEXT NOT NULL,
            withholding_amount TEXT NOT NULL,
            net_amount TEXT NOT NULL,
            credited_currency TEXT NOT NULL,
            conversion_rate TEXT,
            entitlement_quantity TEXT NOT NULL
        )
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


def store_cash_snapshot(ledger: EncryptedLedger, snapshot: BrokerCashSnapshot) -> bool:
    with ledger.connection() as connection:
        initialize(connection)
        return _insert_cash_snapshot(connection, snapshot).rowcount == 1


def store_cash_flow(ledger: EncryptedLedger, flow: BrokerCashFlow) -> bool:
    with ledger.connection() as connection:
        initialize(connection)
        return _insert_cash_flow(connection, flow).rowcount == 1


def store_dividend_declaration(ledger: EncryptedLedger, declaration: BrokerDividendDeclaration) -> bool:
    with ledger.connection() as connection:
        initialize(connection)
        return _insert_dividend_declaration(connection, declaration).rowcount == 1


def store_fee_record(ledger: EncryptedLedger, fee: BrokerFeeRecord) -> bool:
    with ledger.connection() as connection:
        initialize(connection)
        return _insert_fee_record(connection, fee).rowcount == 1


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


def _insert_cash_snapshot(connection: sqlite3.Connection, snapshot: BrokerCashSnapshot) -> sqlite3.Cursor:
    return connection.execute(
        """
        INSERT OR IGNORE INTO broker_cash_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot.source.provider_id,
            snapshot.source.source_hash,
            snapshot.source.record_id,
            snapshot.account.provider_id,
            snapshot.account.account_id,
            snapshot.account.name,
            snapshot.currency.value,
            str(snapshot.amount),
            snapshot.observed_at.isoformat(),
        ),
    )


def _insert_cash_flow(connection: sqlite3.Connection, flow: BrokerCashFlow) -> sqlite3.Cursor:
    return connection.execute(
        """
        INSERT OR IGNORE INTO broker_cash_flows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            flow.source.provider_id,
            flow.source.source_hash,
            flow.source.record_id,
            flow.account.provider_id,
            flow.account.account_id,
            flow.account.name,
            flow.clearing_date.isoformat(),
            flow.settlement_date.isoformat(),
            flow.currency.value,
            flow.flow_type,
            flow.direction,
            str(flow.amount),
            flow.remark,
        ),
    )


def _insert_dividend_declaration(
    connection: sqlite3.Connection, declaration: BrokerDividendDeclaration
) -> sqlite3.Cursor:
    instrument = declaration.instrument
    return connection.execute(
        """
        INSERT OR IGNORE INTO broker_dividend_declarations VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            declaration.source.provider_id,
            declaration.source.source_hash,
            declaration.source.record_id,
            declaration.raw_source_hash,
            declaration.account.provider_id,
            declaration.account.account_id,
            declaration.account.name,
            instrument.symbol,
            instrument.market,
            instrument.currency.value,
            instrument.name,
            None if declaration.announced_at is None else declaration.announced_at.isoformat(),
            declaration.status,
            None if declaration.record_date is None else declaration.record_date.isoformat(),
            None if declaration.ex_date is None else declaration.ex_date.isoformat(),
            None if declaration.payable_date is None else declaration.payable_date.isoformat(),
            declaration.statement,
            None if declaration.amount_per_share is None else str(declaration.amount_per_share),
            None if declaration.currency is None else declaration.currency.value,
        ),
    )


def _insert_fee_record(connection: sqlite3.Connection, fee: BrokerFeeRecord) -> sqlite3.Cursor:
    return connection.execute(
        """
        INSERT OR IGNORE INTO broker_fee_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fee.source.provider_id,
            fee.source.source_hash,
            fee.source.record_id,
            fee.raw_source_hash,
            fee.account.provider_id,
            fee.account.account_id,
            fee.account.name,
            fee.currency.value,
            str(fee.amount),
            fee.classification,
            fee.transaction_id,
            fee.occurred_at.isoformat(),
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


def list_cash_snapshots(ledger: EncryptedLedger) -> list[BrokerCashSnapshot]:
    with ledger.connection() as connection:
        initialize(connection)
        rows = connection.execute(
            """
            SELECT * FROM broker_cash_snapshots
            ORDER BY observed_at, source_provider_id, source_hash, source_record_id
            """
        ).fetchall()
    return [_cash_snapshot_from_row(row) for row in rows]


def list_cash_flows(ledger: EncryptedLedger) -> list[BrokerCashFlow]:
    with ledger.connection() as connection:
        initialize(connection)
        rows = connection.execute(
            """
            SELECT * FROM broker_cash_flows
            ORDER BY clearing_date, settlement_date, source_provider_id, source_hash, source_record_id
            """
        ).fetchall()
    return [_cash_flow_from_row(row) for row in rows]


def list_dividend_declarations(ledger: EncryptedLedger) -> list[BrokerDividendDeclaration]:
    with ledger.connection() as connection:
        initialize(connection)
        rows = connection.execute(
            """
            SELECT * FROM broker_dividend_declarations
            ORDER BY payable_date, record_date, source_provider_id, source_hash, source_record_id
            """
        ).fetchall()
    return [_dividend_declaration_from_row(row) for row in rows]


def list_dividend_credit_mappings(ledger: EncryptedLedger) -> list[DividendCreditMapping]:
    with ledger.connection() as connection:
        initialize(connection)
        rows = connection.execute(
            """
            SELECT * FROM dividend_credit_mappings
            ORDER BY declaration_source_key
            """
        ).fetchall()
    return [_dividend_credit_mapping_from_row(row) for row in rows]


def list_fee_records(ledger: EncryptedLedger) -> list[BrokerFeeRecord]:
    with ledger.connection() as connection:
        initialize(connection)
        rows = connection.execute(
            """
            SELECT * FROM broker_fee_records
            ORDER BY occurred_at, source_provider_id, source_hash, source_record_id
            """
        ).fetchall()
    return [_fee_record_from_row(row) for row in rows]


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


def _cash_snapshot_from_row(row: sqlite3.Row) -> BrokerCashSnapshot:
    return BrokerCashSnapshot(
        source=SourceProvenance(
            row["source_provider_id"], row["source_hash"], row["source_record_id"]
        ),
        account=Account(row["account_provider_id"], row["account_id"], row["account_name"]),
        currency=Currency(row["currency"]),
        amount=Decimal(row["amount"]),
        observed_at=datetime.fromisoformat(row["observed_at"]),
    )


def _cash_flow_from_row(row: sqlite3.Row) -> BrokerCashFlow:
    return BrokerCashFlow(
        source=SourceProvenance(
            row["source_provider_id"], row["source_hash"], row["source_record_id"]
        ),
        account=Account(row["account_provider_id"], row["account_id"], row["account_name"]),
        clearing_date=date.fromisoformat(row["clearing_date"]),
        settlement_date=date.fromisoformat(row["settlement_date"]),
        currency=Currency(row["currency"]),
        flow_type=row["flow_type"],
        direction=row["direction"],
        amount=Decimal(row["amount"]),
        remark=row["remark"],
    )


def _dividend_declaration_from_row(row: sqlite3.Row) -> BrokerDividendDeclaration:
    return BrokerDividendDeclaration(
        source=SourceProvenance(
            row["source_provider_id"], row["source_hash"], row["source_record_id"]
        ),
        raw_source_hash=row["raw_source_hash"],
        account=Account(row["account_provider_id"], row["account_id"], row["account_name"]),
        instrument=Instrument(
            row["instrument_symbol"],
            row["instrument_market"],
            Currency(row["instrument_currency"]),
            row["instrument_name"],
        ),
        announced_at=None if row["announced_at"] is None else date.fromisoformat(row["announced_at"]),
        status=row["status"],
        record_date=None if row["record_date"] is None else date.fromisoformat(row["record_date"]),
        ex_date=None if row["ex_date"] is None else date.fromisoformat(row["ex_date"]),
        payable_date=None if row["payable_date"] is None else date.fromisoformat(row["payable_date"]),
        statement=row["statement"],
        amount_per_share=None if row["amount_per_share"] is None else Decimal(row["amount_per_share"]),
        currency=None if row["currency"] is None else Currency(row["currency"]),
    )


def _dividend_credit_mapping_from_row(row: sqlite3.Row) -> DividendCreditMapping:
    return DividendCreditMapping(
        declaration_source_key=row["declaration_source_key"],
        cash_flow_source_key=row["cash_flow_source_key"],
        cash_snapshot_source_key=row["cash_snapshot_source_key"],
        event_fingerprint=row["event_fingerprint"],
        gross_currency=Currency(row["gross_currency"]),
        gross_amount=Decimal(row["gross_amount"]),
        withholding_amount=Decimal(row["withholding_amount"]),
        net_amount=Decimal(row["net_amount"]),
        credited_currency=Currency(row["credited_currency"]),
        conversion_rate=(
            None if row["conversion_rate"] is None else Decimal(row["conversion_rate"])
        ),
        entitlement_quantity=Decimal(row["entitlement_quantity"]),
    )


_MARKET_TIMEZONES = {
    "HK": "Asia/Hong_Kong",
    "SG": "Asia/Singapore",
    "SH": "Asia/Shanghai",
    "SZ": "Asia/Shanghai",
    "US": "America/New_York",
}


def credit_mapped_dividend(
    ledger: EncryptedLedger,
    account: Account,
    *,
    declaration_record_id: str,
    cash_flow_record_id: str,
    cash_snapshot_record_id: str,
    gross_currency: Currency,
    gross_amount: Decimal | str,
    withholding_amount: Decimal | str,
    conversion_rate: Decimal | str | None,
    allow_currency_conversion: bool,
    confirm_reconciled_funds: bool,
) -> tuple[LedgerEvent, bool]:
    """Credit only an explicitly confirmed declaration-to-cash-flow mapping."""
    if not confirm_reconciled_funds:
        raise LedgerError("dividend mapping requires funds reconciliation confirmation")
    with ledger.connection() as connection:
        initialize(connection)
        declaration = _dividend_declaration_for_record(connection, account, declaration_record_id)
        cash_flow = _cash_flow_for_record(connection, account, cash_flow_record_id)
        cash_snapshot = _cash_snapshot_for_record(connection, account, cash_snapshot_record_id)
        if declaration.record_date is None:
            raise LedgerError("dividend mapping requires a record date")
        if cash_flow.direction.upper() != "IN" or cash_flow.amount <= 0:
            raise LedgerError("dividend mapping requires an inflow cash flow")
        if cash_snapshot.currency != cash_flow.currency:
            raise LedgerError("dividend mapping cash snapshot currency does not match cash flow")
        settlement_at = datetime.combine(cash_flow.settlement_date, time.min, tzinfo=UTC)
        if cash_snapshot.observed_at < settlement_at:
            raise LedgerError("dividend mapping cash snapshot predates settlement")
        latest_snapshot = _latest_cash_snapshot(connection, account, cash_flow.currency)
        if latest_snapshot is None or latest_snapshot.source != cash_snapshot.source:
            raise LedgerError("dividend mapping requires the current cash snapshot")
        if cash_snapshot.amount < cash_flow.amount:
            raise LedgerError("dividend mapping cash snapshot does not cover credited cash")
        entitlement_quantity = _entitlement_quantity(
            connection, account, declaration.instrument, declaration.record_date
        )
        if entitlement_quantity <= 0:
            raise LedgerError("dividend mapping has no record-date entitlement")
        if declaration.currency is not None and declaration.currency != gross_currency:
            raise LedgerError("dividend mapping gross currency conflicts with declaration")
        if gross_currency != cash_flow.currency and not allow_currency_conversion:
            raise LedgerError("dividend currency conversion is disabled in profile settings")
        try:
            gross = decimal(gross_amount)
            withholding = decimal(withholding_amount)
            if (
                declaration.amount_per_share is not None
                and declaration.amount_per_share * entitlement_quantity != gross
            ):
                raise ValueError("dividend gross amount does not match record-date entitlement")
            mapping = DividendCreditMapping(
                declaration.source.key,
                cash_flow.source.key,
                cash_snapshot.source.key,
                "pending",
                gross_currency,
                gross,
                withholding,
                cash_flow.amount,
                cash_flow.currency,
                None if conversion_rate is None else decimal(conversion_rate),
                entitlement_quantity,
            )
        except ValueError as error:
            raise LedgerError(str(error)) from error
        source_payload = {
            "declaration_source": declaration.source.key,
            "cash_flow_source": cash_flow.source.key,
            "cash_snapshot_source": cash_snapshot.source.key,
            "gross_currency": gross_currency.value,
            "gross_amount": str(mapping.gross_amount),
            "withholding_amount": str(mapping.withholding_amount),
            "net_amount": str(mapping.net_amount),
            "conversion_rate": None if mapping.conversion_rate is None else str(mapping.conversion_rate),
        }
        source = SourceProvenance(
            "user", hashlib.sha256(_canonical_json_bytes(source_payload)).hexdigest(),
            f"dividend:{declaration.source.record_id}:{cash_flow.source.record_id}",
        )
        event = LedgerEvent(
            fingerprint=import_fingerprint(source, source_payload),
            source=source,
            account=account,
            occurred_at=settlement_at,
            kind=EventKind.DIVIDEND,
            currency=cash_flow.currency,
            amount=cash_flow.amount,
            instrument=declaration.instrument,
            metadata={
                "confidence": "explicit_user_mapping",
                "declaration_source": declaration.source.key,
                "cash_flow_source": cash_flow.source.key,
                "cash_snapshot_source": cash_snapshot.source.key,
                "gross_currency": gross_currency.value,
                "gross_amount": str(mapping.gross_amount),
                "withholding_amount": str(mapping.withholding_amount),
                "net_credited_amount": str(cash_flow.amount),
                "conversion_rate": (
                    None if mapping.conversion_rate is None else str(mapping.conversion_rate)
                ),
                "entitlement_quantity": str(entitlement_quantity),
                "settlement_date": cash_flow.settlement_date.isoformat(),
                "funds_reconciliation_confirmed": True,
            },
        )
        mapping = DividendCreditMapping(
            mapping.declaration_source_key,
            mapping.cash_flow_source_key,
            mapping.cash_snapshot_source_key,
            event.fingerprint,
            mapping.gross_currency,
            mapping.gross_amount,
            mapping.withholding_amount,
            mapping.net_amount,
            mapping.credited_currency,
            mapping.conversion_rate,
            mapping.entitlement_quantity,
        )
        existing = connection.execute(
            "SELECT * FROM dividend_credit_mappings WHERE declaration_source_key = ?",
            (mapping.declaration_source_key,),
        ).fetchone()
        if existing is not None:
            stored = _dividend_credit_mapping_from_row(existing)
            if stored != mapping:
                raise LedgerError("dividend declaration is already mapped")
            row = connection.execute(
                "SELECT * FROM ledger_events WHERE fingerprint = ?", (stored.event_fingerprint,)
            ).fetchone()
            if row is None:
                raise LedgerError("dividend mapping event is missing")
            return _event_from_row(row), False
        if connection.execute(
            "SELECT 1 FROM dividend_credit_mappings WHERE cash_flow_source_key = ?",
            (mapping.cash_flow_source_key,),
        ).fetchone() is not None:
            raise LedgerError("cash flow is already mapped to a dividend")
        if _insert_event(connection, event).rowcount != 1:
            raise LedgerError("dividend mapping event conflicts with an existing event")
        connection.execute(
            """
            INSERT INTO dividend_credit_mappings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mapping.declaration_source_key,
                mapping.cash_flow_source_key,
                mapping.cash_snapshot_source_key,
                mapping.event_fingerprint,
                mapping.gross_currency.value,
                str(mapping.gross_amount),
                str(mapping.withholding_amount),
                str(mapping.net_amount),
                mapping.credited_currency.value,
                None if mapping.conversion_rate is None else str(mapping.conversion_rate),
                str(mapping.entitlement_quantity),
            ),
        )
    return event, True


def _dividend_declaration_for_record(
    connection: sqlite3.Connection, account: Account, record_id: str
) -> BrokerDividendDeclaration:
    row = _one_broker_record(
        connection, "broker_dividend_declarations", account, record_id, "dividend declaration"
    )
    return _dividend_declaration_from_row(row)


def _cash_flow_for_record(
    connection: sqlite3.Connection, account: Account, record_id: str
) -> BrokerCashFlow:
    row = _one_broker_record(connection, "broker_cash_flows", account, record_id, "cash flow")
    return _cash_flow_from_row(row)


def _cash_snapshot_for_record(
    connection: sqlite3.Connection, account: Account, record_id: str
) -> BrokerCashSnapshot:
    row = _one_broker_record(connection, "broker_cash_snapshots", account, record_id, "cash snapshot")
    return _cash_snapshot_from_row(row)


def _one_broker_record(
    connection: sqlite3.Connection, table: str, account: Account, record_id: str, label: str
) -> sqlite3.Row:
    if not isinstance(record_id, str) or not (identifier := record_id.strip()):
        raise LedgerError(f"{label} record identifier is required")
    rows = connection.execute(
        f"""
        SELECT * FROM {table}
        WHERE account_provider_id = ? AND account_id = ? AND source_record_id = ?
        """,
        (account.provider_id, account.account_id, identifier),
    ).fetchall()
    if len(rows) != 1:
        raise LedgerError(f"{label} record is unavailable")
    return cast(sqlite3.Row, rows[0])


def _latest_cash_snapshot(
    connection: sqlite3.Connection, account: Account, currency: Currency
) -> BrokerCashSnapshot | None:
    row = connection.execute(
        """
        SELECT * FROM broker_cash_snapshots
        WHERE account_provider_id = ? AND account_id = ? AND currency = ?
        ORDER BY observed_at DESC, source_provider_id DESC, source_hash DESC, source_record_id DESC
        LIMIT 1
        """,
        (account.provider_id, account.account_id, currency.value),
    ).fetchone()
    return None if row is None else _cash_snapshot_from_row(row)


def _entitlement_quantity(
    connection: sqlite3.Connection, account: Account, instrument: Instrument, record_date: date
) -> Decimal:
    try:
        from zoneinfo import ZoneInfo

        timezone = ZoneInfo(_MARKET_TIMEZONES[instrument.market])
    except KeyError as error:
        raise LedgerError("dividend instrument market has no record-date timezone") from error
    cutoff = datetime.combine(record_date + timedelta(days=1), time.min, tzinfo=timezone).astimezone(UTC)
    rows = connection.execute(
        "SELECT * FROM ledger_events WHERE occurred_at < ? ORDER BY occurred_at, fingerprint",
        (cutoff.isoformat(),),
    ).fetchall()
    events = [_event_from_row(row) for row in rows]
    return positions(events).get((account.key, instrument.key), Decimal("0"))


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _fee_record_from_row(row: sqlite3.Row) -> BrokerFeeRecord:
    return BrokerFeeRecord(
        source=SourceProvenance(
            row["source_provider_id"], row["source_hash"], row["source_record_id"]
        ),
        raw_source_hash=row["raw_source_hash"],
        account=Account(row["account_provider_id"], row["account_id"], row["account_name"]),
        currency=Currency(row["currency"]),
        amount=Decimal(row["amount"]),
        classification=row["classification"],
        transaction_id=row["transaction_id"],
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
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


def integrity_errors(events: list[LedgerEvent]) -> tuple[str, ...]:
    errors: list[str] = []
    fingerprints = {event.fingerprint for event in events}
    if len(fingerprints) != len(events):
        errors.append("duplicate event fingerprints")
    if len({event.source.key for event in events}) != len(events):
        errors.append("duplicate source records")
    missing_targets = sorted(
        {
            event.corrects_fingerprint
            for event in events
            if event.lifecycle is not EventLifecycle.POSTED
            and event.corrects_fingerprint is not None
            and event.corrects_fingerprint not in fingerprints
        }
    )
    errors.extend(f"missing lifecycle target:{target}" for target in missing_targets)
    corrections = {
        event.fingerprint: event.corrects_fingerprint
        for event in events
        if event.lifecycle is EventLifecycle.CORRECTION
    }
    checked: set[str] = set()
    for start in sorted(corrections):
        chain: list[str] = []
        positions_by_fingerprint: dict[str, int] = {}
        current = start
        while current in corrections and current not in checked:
            if current in positions_by_fingerprint:
                cycle = sorted(chain[positions_by_fingerprint[current] :])
                errors.append(f"correction cycle:{','.join(cycle)}")
                break
            positions_by_fingerprint[current] = len(chain)
            chain.append(current)
            target = corrections[current]
            if target is None:
                break
            current = target
        checked.update(chain)
    try:
        positions(events)
    except LedgerError as error:
        errors.append(str(error))
    return tuple(errors)


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
