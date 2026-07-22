from __future__ import annotations

import csv
import io
import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
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


class QuoteQuality(StrEnum):
    REAL_TIME = "real_time"
    DELAYED = "delayed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class QuoteSnapshot:
    instrument: Instrument
    last_price: Decimal
    observed_at: datetime
    quality: QuoteQuality
    source_hash: str
    vendor_time: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "last_price", decimal(self.last_price))
        if self.last_price <= 0:
            raise ValueError("quote last price must be positive")
        if self.observed_at.tzinfo is None:
            raise ValueError("quote observation time must be timezone-aware")
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))
        if not isinstance(self.quality, QuoteQuality):
            raise ValueError("quote quality is required")
        if len(self.source_hash) != 64:
            raise ValueError("quote source hash must be a SHA-256 digest")


@dataclass(frozen=True)
class PriceFreshness:
    instrument_key: str
    session_date: date
    age: timedelta
    stale: bool


@dataclass(frozen=True)
class FxRate:
    base_currency: Currency
    quote_currency: Currency
    session_date: date
    rate: Decimal
    source_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "rate", decimal(self.rate))
        if self.base_currency is self.quote_currency or self.rate <= 0:
            raise ValueError("FX rate must be positive and use distinct currencies")


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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS fx_rates (
            base_currency TEXT NOT NULL,
            quote_currency TEXT NOT NULL,
            session_date TEXT NOT NULL,
            rate TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            PRIMARY KEY(base_currency, quote_currency, session_date, source_hash)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_price_revisions (
            instrument_key TEXT NOT NULL,
            session_date TEXT NOT NULL,
            close TEXT NOT NULL,
            currency TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            PRIMARY KEY(instrument_key, session_date, source_hash)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS quote_snapshots (
            instrument_key TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            last_price TEXT NOT NULL,
            currency TEXT NOT NULL,
            quality TEXT NOT NULL CHECK(quality IN ('real_time', 'delayed', 'unknown')),
            source_hash TEXT NOT NULL,
            vendor_time TEXT,
            PRIMARY KEY(instrument_key, observed_at, source_hash)
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
            connection.execute(
                """
                INSERT OR IGNORE INTO daily_price_revisions VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    price.instrument.key,
                    price.session_date.isoformat(),
                    str(price.close),
                    price.instrument.currency.value,
                    price.source_hash,
                    datetime.now(UTC).isoformat(),
                ),
            )
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


def historical_prices(ledger: EncryptedLedger, instrument_key: str) -> tuple[tuple[date, Decimal], ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            "SELECT session_date, close FROM daily_prices WHERE instrument_key = ? ORDER BY session_date",
            (instrument_key.upper(),),
        ).fetchall()
    return tuple((date.fromisoformat(row[0]), Decimal(row[1])) for row in rows)


def price_revisions(ledger: EncryptedLedger, instrument_key: str) -> tuple[DailyPrice, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT instrument_key, session_date, close, currency, source_hash
            FROM daily_price_revisions WHERE instrument_key = ?
            ORDER BY session_date, source_hash
            """,
            (instrument_key.upper(),),
        ).fetchall()
    return tuple(
        DailyPrice(
            _instrument_from_key(row["instrument_key"], Currency(row["currency"])),
            date.fromisoformat(row["session_date"]),
            Decimal(row["close"]),
            row["source_hash"],
        )
        for row in rows
    )


def price_freshness(
    ledger: EncryptedLedger,
    instrument_key: str,
    *,
    as_of: date,
    maximum_age_days: int,
) -> PriceFreshness:
    if maximum_age_days < 0:
        raise ValueError("maximum price age must be non-negative")
    prices = historical_prices(ledger, instrument_key)
    if not prices:
        raise ProviderError("no daily price is available")
    session_date, _ = prices[-1]
    age = as_of - session_date
    if age.days < 0:
        raise ProviderError("latest daily price is after requested date")
    return PriceFreshness(instrument_key.upper(), session_date, age, age.days > maximum_age_days)


def store_quote_snapshots(ledger: EncryptedLedger, snapshots: tuple[QuoteSnapshot, ...]) -> int:
    inserted = 0
    with ledger.connection() as connection:
        _initialize(connection)
        for snapshot in snapshots:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO quote_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.instrument.key,
                    snapshot.observed_at.isoformat(),
                    str(snapshot.last_price),
                    snapshot.instrument.currency.value,
                    snapshot.quality.value,
                    snapshot.source_hash,
                    snapshot.vendor_time,
                ),
            )
            inserted += cursor.rowcount
    return inserted


def archive_and_store_quote_snapshots(
    ledger: EncryptedLedger, snapshots: tuple[QuoteSnapshot, ...]
) -> tuple[int, str]:
    content = json.dumps(
        [
            {
                "instrument": snapshot.instrument.key,
                "last_price": str(snapshot.last_price),
                "observed_at": snapshot.observed_at.isoformat(),
                "quality": snapshot.quality.value,
                "vendor_time": snapshot.vendor_time,
            }
            for snapshot in snapshots
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    source_hash = ledger.archive_source(content)
    return store_quote_snapshots(
        ledger, tuple(replace(snapshot, source_hash=source_hash) for snapshot in snapshots)
    ), source_hash


def latest_quote_snapshots(ledger: EncryptedLedger) -> dict[str, QuoteSnapshot]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT first.* FROM quote_snapshots AS first
            JOIN (
                SELECT instrument_key, MAX(observed_at) AS observed_at
                FROM quote_snapshots GROUP BY instrument_key
            ) AS latest USING (instrument_key, observed_at)
            ORDER BY first.instrument_key, first.source_hash
            """
        ).fetchall()
    snapshots: dict[str, QuoteSnapshot] = {}
    for row in rows:
        snapshot = QuoteSnapshot(
            _instrument_from_key(row["instrument_key"], Currency(row["currency"])),
            Decimal(row["last_price"]),
            datetime.fromisoformat(row["observed_at"]),
            QuoteQuality(row["quality"]),
            row["source_hash"],
            row["vendor_time"],
        )
        snapshots[snapshot.instrument.key] = snapshot
    return snapshots


def store_fx_rates(ledger: EncryptedLedger, rates: tuple[FxRate, ...]) -> int:
    inserted = 0
    with ledger.connection() as connection:
        _initialize(connection)
        for rate in rates:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO fx_rates VALUES (?, ?, ?, ?, ?)",
                (
                    rate.base_currency.value,
                    rate.quote_currency.value,
                    rate.session_date.isoformat(),
                    str(rate.rate),
                    rate.source_hash,
                ),
            )
            inserted += cursor.rowcount
    return inserted


def import_fx_rates_csv(ledger: EncryptedLedger, path: Path) -> int:
    content = path.read_bytes()
    source_hash = ledger.archive_source(content)
    try:
        rows = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    except UnicodeDecodeError as error:
        raise ProviderError("FX CSV must be UTF-8") from error
    required = {"date", "base_currency", "quote_currency", "rate"}
    if rows.fieldnames is None or not required <= set(rows.fieldnames):
        raise ProviderError("FX CSV requires date,base_currency,quote_currency,rate")
    rates: list[FxRate] = []
    for row in rows:
        try:
            rates.append(
                FxRate(
                    Currency((row["base_currency"] or "").upper()),
                    Currency((row["quote_currency"] or "").upper()),
                    date.fromisoformat(row["date"] or ""),
                    decimal(row["rate"] or ""),
                    source_hash,
                )
            )
        except (KeyError, ValueError) as error:
            raise ProviderError("FX CSV contains invalid data") from error
    return store_fx_rates(ledger, tuple(rates))


def latest_fx_rates(ledger: EncryptedLedger) -> dict[tuple[Currency, Currency], FxRate]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT first.* FROM fx_rates AS first
            JOIN (
                SELECT base_currency, quote_currency, MAX(session_date) AS session_date
                FROM fx_rates GROUP BY base_currency, quote_currency
            ) AS latest USING (base_currency, quote_currency, session_date)
            ORDER BY first.base_currency, first.quote_currency, first.source_hash
            """
        ).fetchall()
    values: dict[tuple[Currency, Currency], FxRate] = {}
    for row in rows:
        rate = FxRate(
            Currency(row["base_currency"]),
            Currency(row["quote_currency"]),
            date.fromisoformat(row["session_date"]),
            Decimal(row["rate"]),
            row["source_hash"],
        )
        values[(rate.base_currency, rate.quote_currency)] = rate
    return values


def convert_currency(
    amount: Decimal,
    source_currency: Currency,
    target_currency: Currency,
    rates: dict[tuple[Currency, Currency], FxRate],
) -> Decimal:
    if source_currency is target_currency:
        return amount
    direct = rates.get((source_currency, target_currency))
    if direct is not None:
        return amount * direct.rate
    inverse = rates.get((target_currency, source_currency))
    if inverse is not None:
        return amount / inverse.rate
    raise ProviderError(
        f"missing FX rate:{source_currency.value}:{target_currency.value}"
    )


def _instrument_from_key(value: str, currency: Currency) -> Instrument:
    market, separator, symbol = value.partition(":")
    if not separator:
        raise ProviderError("stored market-data instrument key is invalid")
    return Instrument(symbol, market, currency)


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
