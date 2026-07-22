from __future__ import annotations

import sqlite3
from dataclasses import dataclass

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


def add(ledger: EncryptedLedger, item: WatchlistItem) -> bool:
    with ledger.connection() as connection:
        _initialize(connection)
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
    return cursor.rowcount > 0


def remove(ledger: EncryptedLedger, instrument_key: str) -> bool:
    with ledger.connection() as connection:
        _initialize(connection)
        cursor = connection.execute(
            "DELETE FROM watchlist_items WHERE instrument_key = ?", (instrument_key.upper(),)
        )
    return cursor.rowcount > 0


def list_items(ledger: EncryptedLedger) -> tuple[WatchlistItem, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute("SELECT * FROM watchlist_items ORDER BY instrument_key").fetchall()
    return tuple(
        WatchlistItem(
            Instrument(row["symbol"], row["market"], Currency(row["currency"]), row["name"]),
            row["note"],
        )
        for row in rows
    )
