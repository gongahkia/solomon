from __future__ import annotations

import csv
import io
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
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


class QuoteStatus(StrEnum):
    AVAILABLE = "available"
    DELAYED = "delayed"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    UNENTITLED = "unentitled"
    MALFORMED = "malformed"
    EXCESSIVE_SPREAD = "excessive_spread"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class QuoteSnapshot:
    instrument: Instrument
    last_price: Decimal | None
    observed_at: datetime  # retrieval time
    quality: QuoteQuality
    source_hash: str
    vendor_time: str | None = None
    status: QuoteStatus = QuoteStatus.UNKNOWN
    as_of_at: datetime | None = None
    bid_price: Decimal | None = None
    ask_price: Decimal | None = None
    midpoint: Decimal | None = None
    spread: Decimal | None = None
    order_book_as_of: datetime | None = None
    order_book_status: str = "absent"
    market_session: str = "unknown"
    subscription_mode: str = "none"
    provider_fingerprint: str | None = None
    raw_payload: Mapping[str, object] | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.last_price is not None:
            object.__setattr__(self, "last_price", decimal(self.last_price))
            if self.last_price <= 0:
                raise ValueError("quote last price must be positive")
        if self.observed_at.tzinfo is None:
            raise ValueError("quote observation time must be timezone-aware")
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))
        if not isinstance(self.quality, QuoteQuality):
            raise ValueError("quote quality is required")
        if not isinstance(self.status, QuoteStatus):
            raise ValueError("quote status is required")
        if len(self.source_hash) != 64:
            raise ValueError("quote source hash must be a SHA-256 digest")
        for name in ("as_of_at", "order_book_as_of"):
            value = getattr(self, name)
            if value is not None:
                if value.tzinfo is None:
                    raise ValueError(f"quote {name} must be timezone-aware")
                object.__setattr__(self, name, value.astimezone(UTC))
        for name in ("bid_price", "ask_price", "midpoint", "spread"):
            value = getattr(self, name)
            if value is not None:
                value = decimal(value)
                if value < 0 or (name != "spread" and value == 0):
                    raise ValueError(f"quote {name} must be non-negative")
                object.__setattr__(self, name, value)
        if (self.bid_price is None) != (self.ask_price is None):
            raise ValueError("quote bid and ask must both be present or absent")
        bid_price = self.bid_price
        ask_price = self.ask_price
        if bid_price is not None and ask_price is not None:
            if bid_price > ask_price:
                raise ValueError("quote bid must not exceed ask")
            midpoint = (bid_price + ask_price) / Decimal("2")
            spread = ask_price - bid_price
            if self.midpoint != midpoint or self.spread != spread:
                raise ValueError("quote midpoint and spread must match bid and ask")
        elif self.midpoint is not None or self.spread is not None:
            raise ValueError("quote midpoint and spread require bid and ask")
        if not self.order_book_status.strip() or not self.market_session.strip() or not self.subscription_mode.strip():
            raise ValueError("quote status fields must be non-empty")
        fingerprint = self.provider_fingerprint or self.source_hash
        if len(fingerprint) != 64:
            raise ValueError("quote provider fingerprint must be a SHA-256 digest")
        object.__setattr__(self, "provider_fingerprint", fingerprint)

    @property
    def current_price(self) -> Decimal | None:
        if self.status is QuoteStatus.AVAILABLE and self.quality is QuoteQuality.REAL_TIME:
            return self.last_price
        return None


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
    _initialize_quote_snapshots(connection)


def _initialize_quote_snapshots(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(quote_snapshots)")}
    if columns and "status" not in columns:
        connection.execute("ALTER TABLE quote_snapshots RENAME TO quote_snapshots_legacy")
        _create_quote_snapshots_table(connection)
        connection.execute(
            """
            INSERT INTO quote_snapshots (
                instrument_key, observed_at, as_of_at, last_price, currency, quality, status,
                source_hash, provider_fingerprint, vendor_time, bid_price, ask_price, midpoint,
                spread, order_book_as_of, order_book_status, market_session, subscription_mode
            )
            SELECT
                instrument_key, observed_at, NULL, last_price, currency, quality, 'unknown',
                source_hash, source_hash, vendor_time, NULL, NULL, NULL, NULL, NULL, 'absent',
                'unknown', 'none'
            FROM quote_snapshots_legacy
            """
        )
        connection.execute("DROP TABLE quote_snapshots_legacy")
    elif not columns:
        _create_quote_snapshots_table(connection)


def _create_quote_snapshots_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE quote_snapshots (
            instrument_key TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            as_of_at TEXT,
            last_price TEXT,
            currency TEXT NOT NULL,
            quality TEXT NOT NULL CHECK(quality IN ('real_time', 'delayed', 'unknown')),
            status TEXT NOT NULL CHECK(status IN (
                'available', 'delayed', 'unavailable', 'stale', 'unentitled', 'malformed',
                'excessive_spread', 'unknown'
            )),
            source_hash TEXT NOT NULL,
            provider_fingerprint TEXT NOT NULL,
            vendor_time TEXT,
            bid_price TEXT,
            ask_price TEXT,
            midpoint TEXT,
            spread TEXT,
            order_book_as_of TEXT,
            order_book_status TEXT NOT NULL,
            market_session TEXT NOT NULL,
            subscription_mode TEXT NOT NULL,
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
                INSERT OR IGNORE INTO quote_snapshots (
                    instrument_key, observed_at, as_of_at, last_price, currency, quality, status,
                    source_hash, provider_fingerprint, vendor_time, bid_price, ask_price, midpoint,
                    spread, order_book_as_of, order_book_status, market_session, subscription_mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.instrument.key,
                    snapshot.observed_at.isoformat(),
                    snapshot.as_of_at.isoformat() if snapshot.as_of_at is not None else None,
                    str(snapshot.last_price) if snapshot.last_price is not None else None,
                    snapshot.instrument.currency.value,
                    snapshot.quality.value,
                    snapshot.status.value,
                    snapshot.source_hash,
                    snapshot.provider_fingerprint,
                    snapshot.vendor_time,
                    str(snapshot.bid_price) if snapshot.bid_price is not None else None,
                    str(snapshot.ask_price) if snapshot.ask_price is not None else None,
                    str(snapshot.midpoint) if snapshot.midpoint is not None else None,
                    str(snapshot.spread) if snapshot.spread is not None else None,
                    snapshot.order_book_as_of.isoformat()
                    if snapshot.order_book_as_of is not None
                    else None,
                    snapshot.order_book_status,
                    snapshot.market_session,
                    snapshot.subscription_mode,
                ),
            )
            inserted += cursor.rowcount
    return inserted


def archive_and_store_quote_snapshots(
    ledger: EncryptedLedger, snapshots: tuple[QuoteSnapshot, ...]
) -> tuple[int, str]:
    content = json.dumps(
        [
            snapshot.raw_payload
            if snapshot.raw_payload is not None
            else {
                "instrument": snapshot.instrument.key,
                "last_price": str(snapshot.last_price) if snapshot.last_price is not None else None,
                "observed_at": snapshot.observed_at.isoformat(),
                "quality": snapshot.quality.value,
                "status": snapshot.status.value,
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
            Decimal(row["last_price"]) if row["last_price"] is not None else None,
            datetime.fromisoformat(row["observed_at"]),
            QuoteQuality(row["quality"]),
            row["source_hash"],
            row["vendor_time"],
            QuoteStatus(row["status"]),
            datetime.fromisoformat(row["as_of_at"]) if row["as_of_at"] is not None else None,
            Decimal(row["bid_price"]) if row["bid_price"] is not None else None,
            Decimal(row["ask_price"]) if row["ask_price"] is not None else None,
            Decimal(row["midpoint"]) if row["midpoint"] is not None else None,
            Decimal(row["spread"]) if row["spread"] is not None else None,
            datetime.fromisoformat(row["order_book_as_of"])
            if row["order_book_as_of"] is not None
            else None,
            row["order_book_status"],
            row["market_session"],
            row["subscription_mode"],
            row["provider_fingerprint"],
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
