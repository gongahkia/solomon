from __future__ import annotations

import csv
import io
import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from stonks_cli.errors import ProviderError
from stonks_cli.storage import EncryptedLedger
from stonks_cli.types import Currency, Instrument, decimal


@dataclass(frozen=True)
class DailyPrice:
    instrument: Instrument
    session_date: date
    close: Decimal
    source_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "close", decimal(self.close))
        if self.close <= 0:
            raise ValueError("daily close must be positive")


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_prices (
            instrument_key TEXT NOT NULL,
            session_date TEXT NOT NULL,
            close TEXT NOT NULL,
            currency TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            PRIMARY KEY(instrument_key, session_date)
        )
        """
    )


def store_daily_prices(ledger: EncryptedLedger, prices: list[DailyPrice]) -> int:
    inserted = 0
    with ledger.connection() as connection:
        _initialize(connection)
        for price in prices:
            cursor = connection.execute(
                "INSERT OR REPLACE INTO daily_prices VALUES (?, ?, ?, ?, ?)",
                (
                    price.instrument.key,
                    price.session_date.isoformat(),
                    str(price.close),
                    price.instrument.currency.value,
                    price.source_hash,
                ),
            )
            inserted += cursor.rowcount
    return inserted


def archive_and_store_daily_prices(
    ledger: EncryptedLedger, prices: tuple[DailyPrice, ...]
) -> tuple[int, str]:
    if not prices:
        return 0, ledger.archive_source(b"[]")
    content = json.dumps(
        [
            {
                "instrument": price.instrument.key,
                "currency": price.instrument.currency.value,
                "date": price.session_date.isoformat(),
                "close": str(price.close),
            }
            for price in prices
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    source_hash = ledger.archive_source(content)
    return store_daily_prices(ledger, [replace(price, source_hash=source_hash) for price in prices]), source_hash


def latest_prices(ledger: EncryptedLedger) -> dict[str, Decimal]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT first.instrument_key, first.close
            FROM daily_prices AS first
            JOIN (
                SELECT instrument_key, MAX(session_date) AS session_date FROM daily_prices GROUP BY instrument_key
            ) AS latest USING (instrument_key, session_date)
            """
        ).fetchall()
    return {row[0]: Decimal(row[1]) for row in rows}


def import_daily_prices_csv(ledger: EncryptedLedger, path: Path) -> int:
    content = path.read_bytes()
    source_hash = ledger.archive_source(content)
    try:
        rows = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    except UnicodeDecodeError as error:
        raise ProviderError("price CSV must be UTF-8") from error
    required = {"date", "symbol", "market", "currency", "close"}
    if rows.fieldnames is None or not required <= set(rows.fieldnames):
        raise ProviderError("price CSV requires date,symbol,market,currency,close")
    prices: list[DailyPrice] = []
    for row in rows:
        try:
            instrument = Instrument(
                row["symbol"] or "", row["market"] or "", Currency(row["currency"] or "")
            )
            prices.append(
                DailyPrice(
                    instrument,
                    date.fromisoformat(row["date"] or ""),
                    decimal(row["close"] or ""),
                    source_hash,
                )
            )
        except (KeyError, ValueError) as error:
            raise ProviderError("price CSV contains invalid data") from error
    return store_daily_prices(ledger, prices)
