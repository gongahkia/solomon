from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from stonks_cli.storage import EncryptedLedger
from stonks_cli.types import Currency, Instrument


@dataclass(frozen=True)
class WatchlistItem:
    instrument: Instrument
    note: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise ValueError("watchlist instrument is required")
        if self.note is not None:
            note = self.note.strip()
            object.__setattr__(self, "note", note or None)


@dataclass(frozen=True)
class WatchlistSettings:
    restriction_enabled: bool
    version: int

    def __post_init__(self) -> None:
        if not isinstance(self.restriction_enabled, bool):
            raise ValueError("watchlist restriction setting must be boolean")
        if not isinstance(self.version, int) or self.version < 1:
            raise ValueError("watchlist configuration version is invalid")


@dataclass(frozen=True)
class WatchlistAuditEntry:
    changed_at: datetime
    action: str
    source: str
    configuration_version: int
    restriction_enabled: bool
    item: WatchlistItem | None

    def __post_init__(self) -> None:
        if self.changed_at.tzinfo is None:
            raise ValueError("watchlist audit time must be timezone-aware")
        if self.action not in {
            "added",
            "updated",
            "removed",
            "restriction_enabled",
            "restriction_disabled",
        }:
            raise ValueError("watchlist audit action is invalid")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("watchlist audit source is required")
        if not isinstance(self.configuration_version, int) or self.configuration_version < 1:
            raise ValueError("watchlist audit configuration version is invalid")
        if not isinstance(self.restriction_enabled, bool):
            raise ValueError("watchlist audit restriction setting must be boolean")
        object.__setattr__(self, "changed_at", self.changed_at.astimezone(UTC))
        object.__setattr__(self, "source", self.source.strip())


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist_items (
            instrument_key TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            market TEXT NOT NULL,
            currency TEXT NOT NULL,
            name TEXT,
            note TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist_settings (
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
            restriction_enabled INTEGER NOT NULL CHECK(restriction_enabled IN (0, 1)),
            configuration_version INTEGER NOT NULL CHECK(configuration_version >= 1)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist_audit (
            audit_id INTEGER PRIMARY KEY,
            changed_at TEXT NOT NULL,
            action TEXT NOT NULL CHECK(action IN (
                'added', 'updated', 'removed', 'restriction_enabled', 'restriction_disabled'
            )),
            source TEXT NOT NULL,
            configuration_version INTEGER NOT NULL,
            restriction_enabled INTEGER NOT NULL CHECK(restriction_enabled IN (0, 1)),
            instrument_key TEXT,
            symbol TEXT,
            market TEXT,
            currency TEXT,
            name TEXT,
            note TEXT
        )
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO watchlist_settings VALUES (1, 0, 1)
        """
    )


def add(ledger: EncryptedLedger, item: WatchlistItem, *, source: str = "local") -> bool:
    with ledger.connection() as connection:
        _initialize(connection)
        existing = connection.execute(
            "SELECT * FROM watchlist_items WHERE instrument_key = ?", (item.instrument.key,)
        ).fetchone()
        if existing is not None and _item_from_row(existing) == item:
            return False
        cursor = connection.execute(
            """
            INSERT INTO watchlist_items VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(instrument_key) DO UPDATE SET
                name = excluded.name,
                note = excluded.note
            """,
            (
                item.instrument.key,
                item.instrument.symbol,
                item.instrument.market,
                item.instrument.currency.value,
                item.instrument.name,
                item.note,
            ),
        )
        settings = _increment_version(connection)
        _record_audit(
            connection,
            "added" if existing is None else "updated",
            source,
            settings,
            item,
        )
    return cursor.rowcount > 0


def remove(ledger: EncryptedLedger, instrument_key: str, *, source: str = "local") -> bool:
    with ledger.connection() as connection:
        _initialize(connection)
        existing = connection.execute(
            "SELECT * FROM watchlist_items WHERE instrument_key = ?", (instrument_key.upper(),)
        ).fetchone()
        if existing is None:
            return False
        cursor = connection.execute(
            "DELETE FROM watchlist_items WHERE instrument_key = ?", (instrument_key.upper(),)
        )
        settings = _increment_version(connection)
        _record_audit(connection, "removed", source, settings, _item_from_row(existing))
    return cursor.rowcount > 0


def list_items(ledger: EncryptedLedger) -> tuple[WatchlistItem, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute("SELECT * FROM watchlist_items ORDER BY instrument_key").fetchall()
    return tuple(
        _item_from_row(row)
        for row in rows
    )


def settings(ledger: EncryptedLedger) -> WatchlistSettings:
    with ledger.connection() as connection:
        _initialize(connection)
        return _settings_from_row(connection.execute("SELECT * FROM watchlist_settings").fetchone())


def configure_restriction(
    ledger: EncryptedLedger, restriction_enabled: bool, *, source: str = "local"
) -> WatchlistSettings:
    if not isinstance(restriction_enabled, bool):
        raise ValueError("watchlist restriction setting must be boolean")
    with ledger.connection() as connection:
        _initialize(connection)
        current = _settings_from_row(connection.execute("SELECT * FROM watchlist_settings").fetchone())
        if current.restriction_enabled == restriction_enabled:
            return current
        settings = _increment_version(connection, restriction_enabled=restriction_enabled)
        _record_audit(
            connection,
            "restriction_enabled" if restriction_enabled else "restriction_disabled",
            source,
            settings,
            None,
        )
    return settings


def recommendation_allowed(ledger: EncryptedLedger, instrument: Instrument) -> bool:
    if not isinstance(instrument, Instrument):
        raise ValueError("watchlist instrument is required")
    with ledger.connection() as connection:
        _initialize(connection)
        current = _settings_from_row(connection.execute("SELECT * FROM watchlist_settings").fetchone())
        if not current.restriction_enabled:
            return True
        return (
            connection.execute(
                "SELECT 1 FROM watchlist_items WHERE instrument_key = ?", (instrument.key,)
            ).fetchone()
            is not None
        )


def audit_history(ledger: EncryptedLedger) -> tuple[WatchlistAuditEntry, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute("SELECT * FROM watchlist_audit ORDER BY audit_id").fetchall()
    return tuple(
        WatchlistAuditEntry(
            datetime.fromisoformat(row["changed_at"]),
            row["action"],
            row["source"],
            int(row["configuration_version"]),
            bool(row["restriction_enabled"]),
            _item_from_row(row) if row["instrument_key"] is not None else None,
        )
        for row in rows
    )


def _settings_from_row(row: sqlite3.Row | None) -> WatchlistSettings:
    if row is None:
        raise ValueError("watchlist settings are unavailable")
    return WatchlistSettings(bool(row["restriction_enabled"]), int(row["configuration_version"]))


def _increment_version(
    connection: sqlite3.Connection, *, restriction_enabled: bool | None = None
) -> WatchlistSettings:
    current = _settings_from_row(connection.execute("SELECT * FROM watchlist_settings").fetchone())
    settings = WatchlistSettings(
        current.restriction_enabled if restriction_enabled is None else restriction_enabled,
        current.version + 1,
    )
    connection.execute(
        "UPDATE watchlist_settings SET restriction_enabled = ?, configuration_version = ? WHERE singleton = 1",
        (settings.restriction_enabled, settings.version),
    )
    return settings


def _record_audit(
    connection: sqlite3.Connection,
    action: str,
    source: str,
    settings: WatchlistSettings,
    item: WatchlistItem | None,
) -> None:
    source = source.strip()
    if not source:
        raise ValueError("watchlist audit source is required")
    connection.execute(
        """
        INSERT INTO watchlist_audit (
            changed_at, action, source, configuration_version, restriction_enabled, instrument_key,
            symbol, market, currency, name, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(UTC).isoformat(),
            action,
            source,
            settings.version,
            settings.restriction_enabled,
            item.instrument.key if item is not None else None,
            item.instrument.symbol if item is not None else None,
            item.instrument.market if item is not None else None,
            item.instrument.currency.value if item is not None else None,
            item.instrument.name if item is not None else None,
            item.note if item is not None else None,
        ),
    )


def _item_from_row(row: sqlite3.Row) -> WatchlistItem:
    return WatchlistItem(
        Instrument(row["symbol"], row["market"], Currency(row["currency"]), row["name"]),
        row["note"],
    )
