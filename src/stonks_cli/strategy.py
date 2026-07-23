from __future__ import annotations

import csv
import io
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import cast
from uuid import uuid4

from stonks_cli.config import (
    JournalSettings,
    StrategySettings,
    strategy_settings_from_data,
    strategy_settings_to_data,
)
from stonks_cli.errors import ProviderError
from stonks_cli.ledger import list_events
from stonks_cli.storage import EncryptedLedger
from stonks_cli.types import EventKind, EventLifecycle


@dataclass(frozen=True)
class DailyBar:
    close: Decimal
    signal: bool
    split_ratio: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if self.close <= 0:
            raise ValueError("daily close must be positive")
        if self.split_ratio <= 0:
            raise ValueError("split ratio must be positive")


@dataclass(frozen=True)
class BacktestResult:
    total_return: Decimal
    periods: int
    trade_count: int
    strategy_values: tuple[Decimal, ...]


@dataclass(frozen=True)
class StrategyRunCard:
    strategy_name: str
    universe: str
    signal_definition: str
    fee_rate: Decimal
    slippage_rate: Decimal
    source_hash: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                self.strategy_name,
                self.universe,
                self.signal_definition,
                self.source_hash,
            )
        ):
            raise ValueError("strategy run card fields are required")
        if len(self.source_hash) != 64:
            raise ValueError("strategy source hash must be a SHA-256 digest")
        if self.fee_rate < 0 or self.slippage_rate < 0:
            raise ValueError("strategy costs must be non-negative")
        if self.created_at.tzinfo is None:
            raise ValueError("strategy run card time must be timezone-aware")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))


@dataclass(frozen=True)
class StrategyArtifact:
    artifact_id: str
    run_card: StrategyRunCard
    result: BacktestResult
    benchmark_return: Decimal


@dataclass(frozen=True)
class StrategyJournalEntry:
    entry_id: str
    created_at: datetime
    summary: str
    rationale: str

    def __post_init__(self) -> None:
        if not self.entry_id.strip() or not self.summary.strip() or not self.rationale.strip():
            raise ValueError("strategy journal fields are required")
        if self.created_at.tzinfo is None:
            raise ValueError("strategy journal time must be timezone-aware")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))


class AdvisoryJournalDisposition(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PARTIALLY_EXECUTED = "partially_executed"
    DEFERRED = "deferred"
    EXPIRED = "expired"


@dataclass(frozen=True)
class AdvisoryJournalDispositionRecord:
    recorded_at: datetime
    disposition: AdvisoryJournalDisposition
    reason: str | None

    def __post_init__(self) -> None:
        if self.recorded_at.tzinfo is None:
            raise ValueError("journal disposition time must be timezone-aware")
        if not isinstance(self.disposition, AdvisoryJournalDisposition):
            raise ValueError("journal disposition is invalid")
        reason = _optional_journal_text(self.reason)
        object.__setattr__(self, "recorded_at", self.recorded_at.astimezone(UTC))
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True)
class AdvisoryJournalEntry:
    entry_id: str
    advisory_id: str
    profile: str
    configuration_version: str
    opened_at: datetime
    updated_at: datetime
    disposition: AdvisoryJournalDisposition | None
    disposition_at: datetime | None
    reason: str | None
    evidence_fingerprints: tuple[str, ...]
    disposition_history: tuple[AdvisoryJournalDispositionRecord, ...]

    def __post_init__(self) -> None:
        values = (self.entry_id, self.advisory_id, self.profile, self.configuration_version)
        if not all(isinstance(value, str) and value.strip() for value in values):
            raise ValueError("journal identity fields are required")
        if self.opened_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("journal times must be timezone-aware")
        opened_at = self.opened_at.astimezone(UTC)
        updated_at = self.updated_at.astimezone(UTC)
        if updated_at < opened_at:
            raise ValueError("journal update time must not precede opening")
        reason = _optional_journal_text(self.reason)
        if self.disposition is None:
            if self.disposition_at is not None or reason is not None or self.disposition_history:
                raise ValueError("undisposed journal entries cannot include a disposition")
        else:
            if (
                not isinstance(self.disposition, AdvisoryJournalDisposition)
                or self.disposition_at is None
            ):
                raise ValueError("journal disposition timestamp is required")
            if self.disposition_at.tzinfo is None:
                raise ValueError("journal disposition time must be timezone-aware")
            disposition_at = self.disposition_at.astimezone(UTC)
            if (
                disposition_at < opened_at
                or disposition_at > updated_at
                or not self.disposition_history
            ):
                raise ValueError("journal disposition history is invalid")
            if self.disposition_history[-1].disposition is not self.disposition:
                raise ValueError("journal disposition must match its history")
            object.__setattr__(self, "disposition_at", disposition_at)
        if (
            not isinstance(self.evidence_fingerprints, tuple)
            or not all(
                isinstance(value, str) and value.strip() for value in self.evidence_fingerprints
            )
            or len(set(self.evidence_fingerprints)) != len(self.evidence_fingerprints)
        ):
            raise ValueError("journal evidence fingerprints are invalid")
        object.__setattr__(self, "entry_id", self.entry_id.strip())
        object.__setattr__(self, "advisory_id", self.advisory_id.strip())
        object.__setattr__(self, "profile", self.profile.strip())
        object.__setattr__(self, "configuration_version", self.configuration_version.strip())
        object.__setattr__(self, "opened_at", opened_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True)
class JournalSettingsAuditRecord:
    profile: str
    changed_at: datetime
    settings: JournalSettings

    def __post_init__(self) -> None:
        if not isinstance(self.profile, str) or not self.profile.strip():
            raise ValueError("journal settings profile is required")
        if self.changed_at.tzinfo is None or not isinstance(self.settings, JournalSettings):
            raise ValueError("journal settings audit record is invalid")
        object.__setattr__(self, "profile", self.profile.strip())
        object.__setattr__(self, "changed_at", self.changed_at.astimezone(UTC))


@dataclass(frozen=True)
class StrategySettingsAuditRecord:
    profile: str
    changed_at: datetime
    settings: StrategySettings

    def __post_init__(self) -> None:
        if not isinstance(self.profile, str) or not self.profile.strip():
            raise ValueError("strategy settings profile is required")
        if self.changed_at.tzinfo is None or not isinstance(self.settings, StrategySettings):
            raise ValueError("strategy settings audit record is invalid")
        object.__setattr__(self, "profile", self.profile.strip())
        object.__setattr__(self, "changed_at", self.changed_at.astimezone(UTC))


def simulate_eod_long_only(
    bars: Sequence[DailyBar], *, fee_rate: Decimal, slippage_rate: Decimal
) -> BacktestResult:
    if fee_rate < 0 or slippage_rate < 0:
        raise ValueError("fee and slippage rates must be non-negative")
    if len(bars) < 2:
        raise ValueError("at least two daily bars are required")
    value = Decimal("1")
    values = [value]
    trades = 0
    invested = False
    for index in range(1, len(bars)):
        should_hold = bars[index - 1].signal  # signal is known only after the prior close
        if should_hold != invested:
            value *= Decimal("1") - fee_rate - slippage_rate
            trades += 1
            invested = should_hold
        if invested:
            value *= bars[index].close * bars[index].split_ratio / bars[index - 1].close
        values.append(value)
    return BacktestResult(value - Decimal("1"), len(bars) - 1, trades, tuple(values))


def buy_and_hold_return(bars: Sequence[DailyBar]) -> Decimal:
    if len(bars) < 2:
        raise ValueError("at least two daily bars are required")
    value = Decimal("1")
    for index in range(1, len(bars)):
        value *= bars[index].close * bars[index].split_ratio / bars[index - 1].close
    return value - Decimal("1")


def run_csv_backtest(
    ledger: EncryptedLedger, path: Path, *, fee_rate: Decimal, slippage_rate: Decimal
) -> tuple[BacktestResult, str]:
    content = path.read_bytes()
    source_hash = ledger.archive_source(content)
    try:
        rows = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    except UnicodeDecodeError as error:
        raise ProviderError("strategy CSV must be UTF-8") from error
    if rows.fieldnames is None or not {"close", "signal"} <= set(rows.fieldnames):
        raise ProviderError("strategy CSV requires close and signal columns")
    bars: list[DailyBar] = []
    for row in rows:
        signal = (row["signal"] or "").strip().lower()
        if signal not in {"0", "1", "false", "true"}:
            raise ProviderError("strategy signal must be true/false or 1/0")
        bars.append(
            DailyBar(
                Decimal(row["close"] or ""),
                signal in {"1", "true"},
                Decimal(row.get("split_ratio") or "1"),
            )
        )
    return simulate_eod_long_only(bars, fee_rate=fee_rate, slippage_rate=slippage_rate), source_hash


def store_artifact(
    ledger: EncryptedLedger,
    run_card: StrategyRunCard,
    result: BacktestResult,
    benchmark_return: Decimal,
) -> StrategyArtifact:
    artifact = StrategyArtifact(uuid4().hex, run_card, result, Decimal(benchmark_return))
    with ledger.connection() as connection:
        _initialize(connection)
        connection.execute(
            """
            INSERT INTO strategy_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.artifact_id,
                run_card.strategy_name,
                run_card.universe,
                run_card.signal_definition,
                str(run_card.fee_rate),
                str(run_card.slippage_rate),
                run_card.source_hash,
                run_card.created_at.isoformat(),
                str(result.total_return),
                str(benchmark_return),
                result.trade_count,
            ),
        )
    return artifact


def list_artifacts(ledger: EncryptedLedger) -> tuple[StrategyArtifact, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            "SELECT * FROM strategy_artifacts ORDER BY created_at, artifact_id"
        ).fetchall()
    return tuple(
        StrategyArtifact(
            row["artifact_id"],
            StrategyRunCard(
                row["strategy_name"],
                row["universe"],
                row["signal_definition"],
                Decimal(row["fee_rate"]),
                Decimal(row["slippage_rate"]),
                row["source_hash"],
                datetime.fromisoformat(row["created_at"]),
            ),
            BacktestResult(Decimal(row["total_return"]), 0, int(row["trade_count"]), ()),
            Decimal(row["benchmark_return"]),
        )
        for row in rows
    )


def append_journal_entry(
    ledger: EncryptedLedger, summary: str, rationale: str, *, created_at: datetime | None = None
) -> StrategyJournalEntry:
    entry = StrategyJournalEntry(uuid4().hex, created_at or datetime.now(UTC), summary, rationale)
    with ledger.connection() as connection:
        _initialize(connection)
        connection.execute(
            "INSERT INTO strategy_journal VALUES (?, ?, ?, ?)",
            (entry.entry_id, entry.created_at.isoformat(), entry.summary, entry.rationale),
        )
    return entry


def list_journal_entries(ledger: EncryptedLedger) -> tuple[StrategyJournalEntry, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            "SELECT * FROM strategy_journal ORDER BY created_at, entry_id"
        ).fetchall()
    return tuple(
        StrategyJournalEntry(
            row["entry_id"],
            datetime.fromisoformat(row["created_at"]),
            row["summary"],
            row["rationale"],
        )
        for row in rows
    )


def open_advisory_journal(
    ledger: EncryptedLedger,
    advisory_id: str,
    configuration_version: str,
    settings: JournalSettings,
    *,
    opened_at: datetime | None = None,
) -> AdvisoryJournalEntry | None:
    if not isinstance(settings, JournalSettings):
        raise ValueError("journal settings are required")
    if not settings.open_on_advisory:
        return None
    now = _journal_time(opened_at)
    purge_expired_advisory_journal_entries(ledger, settings.retention_days, now=now)
    with ledger.connection() as connection:
        _initialize(connection)
        existing = connection.execute(
            """
            SELECT * FROM advisory_journal_entries
            WHERE advisory_id = ? AND profile = ? AND configuration_version = ?
            ORDER BY opened_at, entry_id LIMIT 1
            """,
            (advisory_id, ledger.config.name, configuration_version),
        ).fetchone()
        if existing is not None:
            return _advisory_journal_entry_from_row(connection, existing)
    entry = AdvisoryJournalEntry(
        uuid4().hex,
        advisory_id,
        ledger.config.name,
        configuration_version,
        now,
        now,
        None,
        None,
        None,
        (),
        (),
    )
    with ledger.connection() as connection:
        _initialize(connection)
        connection.execute(
            """
            INSERT INTO advisory_journal_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.entry_id,
                entry.advisory_id,
                entry.profile,
                entry.configuration_version,
                entry.opened_at.isoformat(),
                entry.updated_at.isoformat(),
                None,
                None,
                None,
            ),
        )
    return entry


def advisory_journal_entry(ledger: EncryptedLedger, entry_id: str) -> AdvisoryJournalEntry | None:
    with ledger.connection() as connection:
        _initialize(connection)
        row = connection.execute(
            "SELECT * FROM advisory_journal_entries WHERE entry_id = ? AND profile = ?",
            (entry_id, ledger.config.name),
        ).fetchone()
        return None if row is None else _advisory_journal_entry_from_row(connection, row)


def record_advisory_journal_disposition(
    ledger: EncryptedLedger,
    entry_id: str,
    disposition: AdvisoryJournalDisposition | str,
    *,
    reason: str | None = None,
    recorded_at: datetime | None = None,
) -> AdvisoryJournalEntry:
    try:
        selected = AdvisoryJournalDisposition(disposition)
    except ValueError as error:
        raise ValueError("journal disposition is invalid") from error
    now = _journal_time(recorded_at)
    normalized_reason = _optional_journal_text(reason)
    with ledger.connection() as connection:
        _initialize(connection)
        row = _advisory_journal_row(connection, ledger, entry_id)
        entry = _advisory_journal_entry_from_row(connection, row)
        if now < entry.updated_at:
            raise ValueError("journal disposition time must not precede the latest entry update")
        connection.execute(
            "INSERT INTO advisory_journal_dispositions VALUES (?, ?, ?, ?, ?)",
            (uuid4().hex, entry.entry_id, now.isoformat(), selected.value, normalized_reason),
        )
        connection.execute(
            """
            UPDATE advisory_journal_entries
            SET updated_at = ?, disposition = ?, disposition_at = ?, reason = ?
            WHERE entry_id = ?
            """,
            (now.isoformat(), selected.value, now.isoformat(), normalized_reason, entry.entry_id),
        )
        updated = _advisory_journal_row(connection, ledger, entry.entry_id)
        return _advisory_journal_entry_from_row(connection, updated)


def link_advisory_journal_evidence(
    ledger: EncryptedLedger,
    entry_id: str,
    event_fingerprint: str,
    *,
    linked_at: datetime | None = None,
) -> AdvisoryJournalEntry:
    normalized_fingerprint = event_fingerprint.strip() if isinstance(event_fingerprint, str) else ""
    if not normalized_fingerprint:
        raise ValueError("journal evidence fingerprint is required")
    event = next(
        (item for item in list_events(ledger) if item.fingerprint == normalized_fingerprint), None
    )
    if (
        event is None
        or event.lifecycle is not EventLifecycle.POSTED
        or event.kind not in {EventKind.BUY, EventKind.SELL}
    ):
        raise ValueError("journal evidence must be an imported posted buy or sell event")
    now = _journal_time(linked_at)
    with ledger.connection() as connection:
        _initialize(connection)
        row = _advisory_journal_row(connection, ledger, entry_id)
        entry = _advisory_journal_entry_from_row(connection, row)
        if entry.disposition not in {
            AdvisoryJournalDisposition.ACCEPTED,
            AdvisoryJournalDisposition.PARTIALLY_EXECUTED,
        }:
            raise ValueError(
                "journal evidence requires an accepted or partially executed disposition"
            )
        if now < entry.updated_at:
            raise ValueError("journal evidence time must not precede the latest entry update")
        inserted = connection.execute(
            "INSERT OR IGNORE INTO advisory_journal_evidence VALUES (?, ?, ?)",
            (entry.entry_id, normalized_fingerprint, now.isoformat()),
        ).rowcount
        if inserted == 1:
            connection.execute(
                "UPDATE advisory_journal_entries SET updated_at = ? WHERE entry_id = ?",
                (now.isoformat(), entry.entry_id),
            )
        updated = _advisory_journal_row(connection, ledger, entry.entry_id)
        return _advisory_journal_entry_from_row(connection, updated)


def list_advisory_journal_entries(
    ledger: EncryptedLedger, *, retention_days: int | None = None, now: datetime | None = None
) -> tuple[AdvisoryJournalEntry, ...]:
    purge_expired_advisory_journal_entries(ledger, retention_days, now=now)
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            "SELECT * FROM advisory_journal_entries WHERE profile = ? ORDER BY opened_at, entry_id",
            (ledger.config.name,),
        ).fetchall()
        return tuple(_advisory_journal_entry_from_row(connection, row) for row in rows)


def purge_expired_advisory_journal_entries(
    ledger: EncryptedLedger, retention_days: int | None, *, now: datetime | None = None
) -> int:
    if retention_days is None:
        return 0
    if (
        not isinstance(retention_days, int)
        or isinstance(retention_days, bool)
        or retention_days < 1
    ):
        raise ValueError("journal retention days must be positive")
    cutoff = _journal_time(now) - timedelta(days=retention_days)
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            "SELECT entry_id FROM advisory_journal_entries WHERE profile = ? AND opened_at < ?",
            (ledger.config.name, cutoff.isoformat()),
        ).fetchall()
        entry_ids = tuple(row["entry_id"] for row in rows)
        if not entry_ids:
            return 0
        placeholders = ", ".join("?" for _ in entry_ids)
        connection.execute(
            f"DELETE FROM advisory_journal_dispositions WHERE entry_id IN ({placeholders})",
            entry_ids,
        )
        connection.execute(
            f"DELETE FROM advisory_journal_evidence WHERE entry_id IN ({placeholders})", entry_ids
        )
        connection.execute(
            f"DELETE FROM advisory_journal_entries WHERE entry_id IN ({placeholders})", entry_ids
        )
    return len(entry_ids)


def record_journal_settings_audit(
    ledger: EncryptedLedger, settings: JournalSettings, *, changed_at: datetime | None = None
) -> JournalSettingsAuditRecord:
    record = JournalSettingsAuditRecord(ledger.config.name, _journal_time(changed_at), settings)
    with ledger.connection() as connection:
        _initialize(connection)
        connection.execute(
            "INSERT INTO advisory_journal_settings_audit VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.profile,
                record.changed_at.isoformat(),
                settings.open_on_advisory,
                settings.retention_days,
                settings.display_reasons,
                settings.version,
            ),
        )
    return record


def journal_settings_audit(ledger: EncryptedLedger) -> tuple[JournalSettingsAuditRecord, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT * FROM advisory_journal_settings_audit
            WHERE profile = ? ORDER BY changed_at, configuration_version
            """,
            (ledger.config.name,),
        ).fetchall()
    return tuple(
        JournalSettingsAuditRecord(
            row["profile"],
            datetime.fromisoformat(row["changed_at"]),
            JournalSettings(
                bool(row["open_on_advisory"]),
                None if row["retention_days"] is None else int(row["retention_days"]),
                bool(row["display_reasons"]),
                int(row["configuration_version"]),
            ),
        )
        for row in rows
    )


def record_strategy_settings_audit(
    ledger: EncryptedLedger, settings: StrategySettings, *, changed_at: datetime | None = None
) -> StrategySettingsAuditRecord:
    record = StrategySettingsAuditRecord(ledger.config.name, _journal_time(changed_at), settings)
    payload = json.dumps(strategy_settings_to_data(settings), sort_keys=True, separators=(",", ":"))
    with ledger.connection() as connection:
        _initialize(connection)
        connection.execute(
            "INSERT INTO strategy_settings_audit VALUES (?, ?, ?, ?)",
            (record.profile, record.changed_at.isoformat(), settings.version, payload),
        )
    return record


def strategy_settings_audit(ledger: EncryptedLedger) -> tuple[StrategySettingsAuditRecord, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT * FROM strategy_settings_audit
            WHERE profile = ? ORDER BY changed_at, configuration_version
            """,
            (ledger.config.name,),
        ).fetchall()
    try:
        return tuple(
            StrategySettingsAuditRecord(
                row["profile"],
                datetime.fromisoformat(row["changed_at"]),
                strategy_settings_from_data(json.loads(row["settings_json"])),
            )
            for row in rows
        )
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("strategy settings audit is invalid") from error


def _optional_journal_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value.strip()) > 4_096:
        raise ValueError("journal reason is invalid")
    return value.strip() or None


def _journal_time(value: datetime | None) -> datetime:
    now = datetime.now(UTC) if value is None else value
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("journal time must be timezone-aware")
    return now.astimezone(UTC)


def _advisory_journal_row(
    connection: sqlite3.Connection, ledger: EncryptedLedger, entry_id: str
) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM advisory_journal_entries WHERE entry_id = ? AND profile = ?",
        (entry_id, ledger.config.name),
    ).fetchone()
    if row is None:
        raise ValueError("journal entry was not found")
    return cast(sqlite3.Row, row)


def _advisory_journal_entry_from_row(
    connection: sqlite3.Connection, row: sqlite3.Row
) -> AdvisoryJournalEntry:
    evidence = tuple(
        item["event_fingerprint"]
        for item in connection.execute(
            "SELECT event_fingerprint FROM advisory_journal_evidence WHERE entry_id = ? ORDER BY linked_at, event_fingerprint",
            (row["entry_id"],),
        ).fetchall()
    )
    history = tuple(
        AdvisoryJournalDispositionRecord(
            datetime.fromisoformat(item["recorded_at"]),
            AdvisoryJournalDisposition(item["disposition"]),
            item["reason"],
        )
        for item in connection.execute(
            "SELECT * FROM advisory_journal_dispositions WHERE entry_id = ? ORDER BY recorded_at, record_id",
            (row["entry_id"],),
        ).fetchall()
    )
    return AdvisoryJournalEntry(
        row["entry_id"],
        row["advisory_id"],
        row["profile"],
        row["configuration_version"],
        datetime.fromisoformat(row["opened_at"]),
        datetime.fromisoformat(row["updated_at"]),
        None if row["disposition"] is None else AdvisoryJournalDisposition(row["disposition"]),
        None if row["disposition_at"] is None else datetime.fromisoformat(row["disposition_at"]),
        row["reason"],
        evidence,
        history,
    )


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_artifacts (
            artifact_id TEXT PRIMARY KEY,
            strategy_name TEXT NOT NULL,
            universe TEXT NOT NULL,
            signal_definition TEXT NOT NULL,
            fee_rate TEXT NOT NULL,
            slippage_rate TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            total_return TEXT NOT NULL,
            benchmark_return TEXT NOT NULL,
            trade_count INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_journal (
            entry_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            summary TEXT NOT NULL,
            rationale TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS advisory_journal_entries (
            entry_id TEXT PRIMARY KEY,
            advisory_id TEXT NOT NULL,
            profile TEXT NOT NULL,
            configuration_version TEXT NOT NULL,
            opened_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            disposition TEXT CHECK(disposition IN (
                'accepted', 'rejected', 'partially_executed', 'deferred', 'expired'
            )),
            disposition_at TEXT,
            reason TEXT,
            CHECK(
                (disposition IS NULL AND disposition_at IS NULL AND reason IS NULL)
                OR (disposition IS NOT NULL AND disposition_at IS NOT NULL)
            )
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS advisory_journal_dispositions (
            record_id TEXT PRIMARY KEY,
            entry_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            disposition TEXT NOT NULL CHECK(disposition IN (
                'accepted', 'rejected', 'partially_executed', 'deferred', 'expired'
            )),
            reason TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS advisory_journal_evidence (
            entry_id TEXT NOT NULL,
            event_fingerprint TEXT NOT NULL,
            linked_at TEXT NOT NULL,
            PRIMARY KEY(entry_id, event_fingerprint)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS advisory_journal_settings_audit (
            profile TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            open_on_advisory INTEGER NOT NULL,
            retention_days INTEGER,
            display_reasons INTEGER NOT NULL,
            configuration_version INTEGER NOT NULL,
            PRIMARY KEY(profile, changed_at, configuration_version)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_settings_audit (
            profile TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            configuration_version INTEGER NOT NULL,
            settings_json TEXT NOT NULL,
            PRIMARY KEY(profile, changed_at, configuration_version)
        )
        """
    )
