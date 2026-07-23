from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from stonks_cli.errors import ProviderError
from stonks_cli.storage import EncryptedLedger
from stonks_cli.types import (
    Account,
    AssetClass,
    Currency,
    ETFClassification,
    GICSSector,
    Instrument,
    InstrumentMaster,
    ListingStatus,
    MoomooInstrumentEligibility,
    decimal,
)

_US_TICKER = re.compile(r"[A-Z0-9][A-Z0-9.-]*\Z")
_SG_TICKER = re.compile(r"[A-Z0-9][A-Z0-9.-]*\Z")
_MAS_EXCHANGE_RATES_URL = "https://eservices.mas.gov.sg/statistics/msb/exchangerates.aspx"
_MAS_PROVIDER_ID = "mas"
_MAS_TIMEZONE = ZoneInfo("Asia/Singapore")
_MAS_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
_MAS_FORM_HIDDEN_FIELDS = frozenset({"__VIEWSTATE", "__EVENTVALIDATION", "__VIEWSTATEGENERATOR"})


class _MasExchangeRatesFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "input":
            return
        values = {name.lower(): value for name, value in attrs}
        name = values.get("name")
        value = values.get("value")
        if name in _MAS_FORM_HIDDEN_FIELDS and value:
            self.fields[name] = value


@dataclass(frozen=True)
class DailyPrice:
    instrument: Instrument
    session_date: date
    close: Decimal
    source_hash: str
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "close", decimal(self.close))
        if self.close <= 0:
            raise ValueError("daily close must be positive")
        for name in ("open", "high", "low"):
            value = getattr(self, name)
            if value is not None:
                value = decimal(value)
                if value <= 0:
                    raise ValueError(f"daily {name} must be positive")
                object.__setattr__(self, name, value)
        if any(value is not None for value in (self.open, self.high, self.low)):
            if self.open is None or self.high is None or self.low is None:
                raise ValueError("daily OHLC must be complete")
            if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
                raise ValueError("daily OHLC ordering is invalid")

    @property
    def has_complete_ohlc(self) -> bool:
        return self.open is not None


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


class MarketSession(StrEnum):
    PRE_MARKET = "pre_market"
    OPENING = "opening"
    REGULAR = "regular"
    BREAK = "break"
    AFTER_HOURS = "after_hours"
    OVERNIGHT = "overnight"
    CLOSED = "closed"
    UNKNOWN = "unknown"


_MARKET_SESSION_STATES = {
    "US": {
        "PRE_MARKET_BEGIN": MarketSession.PRE_MARKET,
        "AFTERNOON": MarketSession.REGULAR,
        "AFTER_HOURS_BEGIN": MarketSession.AFTER_HOURS,
        "AFTER_HOURS_END": MarketSession.CLOSED,
        "OVERNIGHT": MarketSession.OVERNIGHT,
    },
    "SG": {
        "WAITING_OPEN": MarketSession.OPENING,
        "MORNING": MarketSession.REGULAR,
        "REST": MarketSession.BREAK,
        "AFTERNOON": MarketSession.REGULAR,
        "CLOSED": MarketSession.CLOSED,
    },
}


def normalize_market_session(market: str, value: str | None) -> MarketSession:
    normalized = value.strip().upper() if value is not None else ""
    return _MARKET_SESSION_STATES.get(market.strip().upper(), {}).get(normalized, MarketSession.UNKNOWN)


@dataclass(frozen=True)
class QuoteSnapshot:
    instrument: Instrument
    last_price: Decimal | None
    observed_at: datetime
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
    market_session: MarketSession = MarketSession.UNKNOWN
    subscription_mode: str = "none"
    provider_fingerprint: str | None = None
    raw_payload: Mapping[str, object] | None = field(default=None, compare=False, repr=False)
    market_session_raw: str = "unknown"

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
        if not isinstance(self.market_session, MarketSession):
            raise ValueError("quote market session is required")
        if (
            not self.order_book_status.strip()
            or not self.subscription_mode.strip()
            or not self.market_session_raw.strip()
        ):
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
    as_of_at: datetime | None = None
    provider_id: str = "csv"
    as_of_precision: FxAsOfPrecision | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.base_currency, Currency) or not isinstance(self.quote_currency, Currency):
            raise ValueError("FX currencies are required")
        if {self.base_currency, self.quote_currency} != {Currency.USD, Currency.SGD}:
            raise ValueError("only USD/SGD FX pairs are supported")
        if not isinstance(self.session_date, date):
            raise ValueError("FX session date is required")
        object.__setattr__(self, "rate", decimal(self.rate))
        if self.base_currency is self.quote_currency or self.rate <= 0:
            raise ValueError("FX rate must be positive and use distinct currencies")
        supplied_as_of_at = self.as_of_at
        as_of_at = supplied_as_of_at or datetime(
            self.session_date.year, self.session_date.month, self.session_date.day, tzinfo=UTC
        )
        if as_of_at.tzinfo is None:
            raise ValueError("FX as-of time must be timezone-aware")
        as_of_at = as_of_at.astimezone(UTC)
        if as_of_at.date() != self.session_date:
            raise ValueError("FX as-of time must match its session date")
        precision = self.as_of_precision or (
            FxAsOfPrecision.INSTANT if supplied_as_of_at is not None else FxAsOfPrecision.DATE
        )
        if not isinstance(precision, FxAsOfPrecision):
            raise ValueError("FX as-of precision is invalid")
        provider_id = self.provider_id.strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", provider_id):
            raise ValueError("FX provider identifier is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_hash.lower()):
            raise ValueError("FX source hash must be a SHA-256 digest")
        object.__setattr__(self, "as_of_at", as_of_at)
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "source_hash", self.source_hash.lower())
        object.__setattr__(self, "as_of_precision", precision)


class FxAsOfPrecision(StrEnum):
    DATE = "date"
    INSTANT = "instant"


@dataclass(frozen=True)
class FxRateFreshness:
    rate: FxRate
    as_of_at: datetime
    age: timedelta
    stale: bool


@dataclass(frozen=True)
class FxRateResolution:
    source_currency: Currency
    target_currency: Currency
    rate: FxRate | None
    conversion_rate: Decimal
    inverted: bool


@dataclass(frozen=True)
class FxReferenceRefresh:
    provider_id: str
    source_url: str
    start_date: date
    end_date: date
    source_hash: str
    fetched_rates: int
    persisted_rates: int


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_prices (
            instrument_key TEXT NOT NULL,
            session_date TEXT NOT NULL,
            close TEXT NOT NULL,
            open TEXT,
            high TEXT,
            low TEXT,
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
            as_of_at TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            as_of_precision TEXT NOT NULL CHECK(as_of_precision IN ('date', 'instant')),
            PRIMARY KEY(base_currency, quote_currency, session_date, source_hash)
        )
        """
    )
    _initialize_fx_rates(connection)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_price_revisions (
            instrument_key TEXT NOT NULL,
            session_date TEXT NOT NULL,
            close TEXT NOT NULL,
            open TEXT,
            high TEXT,
            low TEXT,
            currency TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            PRIMARY KEY(instrument_key, session_date, source_hash)
        )
        """
    )
    _initialize_instrument_master(connection)
    _initialize_daily_price_ohlc(connection)
    _initialize_quote_snapshots(connection)


def _initialize_instrument_master(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS instrument_master_versions (
            canonical_id TEXT NOT NULL,
            exchange TEXT NOT NULL,
            market TEXT NOT NULL CHECK(market IN ('US', 'SG')),
            currency TEXT NOT NULL,
            asset_class TEXT NOT NULL CHECK(asset_class IN ('equity', 'etf', 'reit', 'index')),
            provider_symbol TEXT NOT NULL,
            listing_status TEXT NOT NULL CHECK(listing_status IN ('listed', 'delisted', 'suspended', 'unknown')),
            metadata_version TEXT NOT NULL,
            metadata_source_hash TEXT NOT NULL,
            etf_classification TEXT CHECK(etf_classification IN ('broad_diversified', 'sector_narrow')),
            classification_version TEXT,
            margin_only INTEGER NOT NULL CHECK(margin_only IN (0, 1)),
            short_only INTEGER NOT NULL CHECK(short_only IN (0, 1)),
            leveraged INTEGER NOT NULL CHECK(leveraged IN (0, 1)),
            inverse_product INTEGER NOT NULL CHECK(inverse_product IN (0, 1)),
            sector TEXT CHECK(sector IN (
                'energy', 'materials', 'industrials', 'consumer_discretionary', 'consumer_staples',
                'health_care', 'financials', 'information_technology', 'communication_services',
                'utilities', 'real_estate'
            )),
            sector_version TEXT,
            sector_source_hash TEXT,
            recorded_at TEXT NOT NULL,
            PRIMARY KEY(canonical_id, metadata_version, metadata_source_hash)
        )
        """
    )
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(instrument_master_versions)")}
    for name in ("sector", "sector_version", "sector_source_hash"):
        if name not in columns:
            connection.execute(f"ALTER TABLE instrument_master_versions ADD COLUMN {name} TEXT")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS moomoo_instrument_eligibility (
            canonical_id TEXT NOT NULL,
            account_key TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            available INTEGER NOT NULL CHECK(available IN (0, 1)),
            cash_buy_eligible INTEGER NOT NULL CHECK(cash_buy_eligible IN (0, 1)),
            settled_cash_available INTEGER NOT NULL CHECK(settled_cash_available IN (0, 1)),
            PRIMARY KEY(canonical_id, account_key, observed_at, source_hash)
        )
        """
    )


def _initialize_fx_rates(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(fx_rates)")}
    if "as_of_at" not in columns:
        connection.execute("ALTER TABLE fx_rates ADD COLUMN as_of_at TEXT")
        connection.execute(
            "UPDATE fx_rates SET as_of_at = session_date || 'T00:00:00+00:00' WHERE as_of_at IS NULL"
        )
    if "provider_id" not in columns:
        connection.execute("ALTER TABLE fx_rates ADD COLUMN provider_id TEXT NOT NULL DEFAULT 'csv'")
    if "as_of_precision" not in columns:
        connection.execute(
            "ALTER TABLE fx_rates ADD COLUMN as_of_precision TEXT NOT NULL DEFAULT 'date'"
        )


def _initialize_daily_price_ohlc(connection: sqlite3.Connection) -> None:
    for table in ("daily_prices", "daily_price_revisions"):
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        for name in ("open", "high", "low"):
            if name not in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} TEXT")


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
                spread, order_book_as_of, order_book_status, market_session, market_session_raw,
                subscription_mode
            )
            SELECT
                instrument_key, observed_at, NULL, last_price, currency, quality, 'unknown',
                source_hash, source_hash, vendor_time, NULL, NULL, NULL, NULL, NULL, 'absent',
                'unknown', 'unknown', 'none'
            FROM quote_snapshots_legacy
            """
        )
        connection.execute("DROP TABLE quote_snapshots_legacy")
    elif not columns:
        _create_quote_snapshots_table(connection)
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(quote_snapshots)")}
    if "market_session_raw" not in columns:
        connection.execute(
            "ALTER TABLE quote_snapshots ADD COLUMN market_session_raw TEXT NOT NULL DEFAULT 'unknown'"
        )
        rows = connection.execute(
            "SELECT instrument_key, observed_at, source_hash, market_session FROM quote_snapshots"
        ).fetchall()
        for row in rows:
            market, _, _ = row["instrument_key"].partition(":")
            raw = row["market_session"]
            connection.execute(
                """
                UPDATE quote_snapshots
                SET market_session = ?, market_session_raw = ?
                WHERE instrument_key = ? AND observed_at = ? AND source_hash = ?
                """,
                (
                    normalize_market_session(market, raw).value,
                    raw,
                    row["instrument_key"],
                    row["observed_at"],
                    row["source_hash"],
                ),
            )


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
            market_session_raw TEXT NOT NULL,
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
                """
                INSERT OR REPLACE INTO daily_prices (
                    instrument_key, session_date, close, open, high, low, currency, source_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    price.instrument.key,
                    price.session_date.isoformat(),
                    str(price.close),
                    str(price.open) if price.open is not None else None,
                    str(price.high) if price.high is not None else None,
                    str(price.low) if price.low is not None else None,
                    price.instrument.currency.value,
                    price.source_hash,
                ),
            )
            inserted += cursor.rowcount
            connection.execute(
                """
                INSERT OR IGNORE INTO daily_price_revisions (
                    instrument_key, session_date, close, open, high, low, currency, source_hash,
                    recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    price.instrument.key,
                    price.session_date.isoformat(),
                    str(price.close),
                    str(price.open) if price.open is not None else None,
                    str(price.high) if price.high is not None else None,
                    str(price.low) if price.low is not None else None,
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
                "open": str(price.open) if price.open is not None else None,
                "high": str(price.high) if price.high is not None else None,
                "low": str(price.low) if price.low is not None else None,
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


def latest_daily_price_records(ledger: EncryptedLedger) -> dict[str, DailyPrice]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT first.instrument_key, first.session_date, first.close, first.open, first.high, first.low,
                   first.currency, first.source_hash
            FROM daily_prices AS first
            JOIN (
                SELECT instrument_key, MAX(session_date) AS session_date
                FROM daily_prices GROUP BY instrument_key
            ) AS latest USING (instrument_key, session_date)
            """
        ).fetchall()
    return {
        row["instrument_key"]: DailyPrice(
            _instrument_from_key(row["instrument_key"], Currency(row["currency"])),
            date.fromisoformat(row["session_date"]),
            Decimal(row["close"]),
            row["source_hash"],
            Decimal(row["open"]) if row["open"] is not None else None,
            Decimal(row["high"]) if row["high"] is not None else None,
            Decimal(row["low"]) if row["low"] is not None else None,
        )
        for row in rows
    }


def historical_prices(ledger: EncryptedLedger, instrument_key: str) -> tuple[tuple[date, Decimal], ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            "SELECT session_date, close FROM daily_prices WHERE instrument_key = ? ORDER BY session_date",
            (instrument_key.upper(),),
        ).fetchall()
    return tuple((date.fromisoformat(row[0]), Decimal(row[1])) for row in rows)


def historical_daily_price_records(
    ledger: EncryptedLedger, instrument_key: str
) -> tuple[DailyPrice, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT instrument_key, session_date, close, open, high, low, currency, source_hash
            FROM daily_prices WHERE instrument_key = ? ORDER BY session_date
            """,
            (instrument_key.upper(),),
        ).fetchall()
    return tuple(
        DailyPrice(
            _instrument_from_key(row["instrument_key"], Currency(row["currency"])),
            date.fromisoformat(row["session_date"]),
            Decimal(row["close"]),
            row["source_hash"],
            Decimal(row["open"]) if row["open"] is not None else None,
            Decimal(row["high"]) if row["high"] is not None else None,
            Decimal(row["low"]) if row["low"] is not None else None,
        )
        for row in rows
    )


def price_revisions(ledger: EncryptedLedger, instrument_key: str) -> tuple[DailyPrice, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT instrument_key, session_date, close, open, high, low, currency, source_hash
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
            Decimal(row["open"]) if row["open"] is not None else None,
            Decimal(row["high"]) if row["high"] is not None else None,
            Decimal(row["low"]) if row["low"] is not None else None,
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
                    spread, order_book_as_of, order_book_status, market_session, subscription_mode,
                    market_session_raw
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    snapshot.market_session_raw,
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
            MarketSession(row["market_session"]),
            row["subscription_mode"],
            row["provider_fingerprint"],
            market_session_raw=row["market_session_raw"],
        )
        snapshots[snapshot.instrument.key] = snapshot
    return snapshots


def refresh_mas_usd_sgd_reference_rates(
    ledger: EncryptedLedger,
    start_date: date,
    end_date: date,
    *,
    timeout: float = 20,
) -> FxReferenceRefresh:
    if not isinstance(start_date, date) or not isinstance(end_date, date):
        raise ValueError("MAS FX date range is required")
    if start_date > end_date:
        raise ValueError("MAS FX start date must not be after end date")
    if timeout <= 0:
        raise ValueError("MAS FX timeout must be positive")
    content = _download_mas_usd_sgd_csv(start_date, end_date, timeout)
    observations = _parse_mas_usd_sgd_csv(content, start_date, end_date)
    source_hash = ledger.archive_source(content)
    rates = tuple(
        FxRate(
            Currency.USD,
            Currency.SGD,
            session_date,
            rate,
            source_hash,
            datetime.combine(session_date, time(12), tzinfo=_MAS_TIMEZONE),
            _MAS_PROVIDER_ID,
            FxAsOfPrecision.INSTANT,
        )
        for session_date, rate in observations
    )
    return FxReferenceRefresh(
        _MAS_PROVIDER_ID,
        _MAS_EXCHANGE_RATES_URL,
        start_date,
        end_date,
        source_hash,
        len(rates),
        store_fx_rates(ledger, rates),
    )


def _download_mas_usd_sgd_csv(start_date: date, end_date: date, timeout: float) -> bytes:
    form_request = Request(_MAS_EXCHANGE_RATES_URL, headers={"Accept": "text/html"})
    form = _read_mas_response(form_request, timeout, expected_content_type="text/html")
    parser = _MasExchangeRatesFormParser()
    try:
        parser.feed(form.decode("utf-8"))
        parser.close()
    except (UnicodeDecodeError, ValueError) as error:
        raise ProviderError("MAS FX form is malformed") from error
    missing = {"__VIEWSTATE", "__EVENTVALIDATION"} - set(parser.fields)
    if missing:
        raise ProviderError("MAS FX form is missing required fields")
    payload = {
        **parser.fields,
        "ctl00$ContentPlaceHolder1$StartYearDropDownList": str(start_date.year),
        "ctl00$ContentPlaceHolder1$EndYearDropDownList": str(end_date.year),
        "ctl00$ContentPlaceHolder1$StartMonthDropDownList": str(start_date.month),
        "ctl00$ContentPlaceHolder1$EndMonthDropDownList": str(end_date.month),
        "ctl00$ContentPlaceHolder1$FrequencyDropDownList": "D",
        "ctl00$ContentPlaceHolder1$EndOfPeriodPerUnitCheckBoxList$2": "on",
        "ctl00$ContentPlaceHolder1$DownloadButton": "Download",
    }
    download_request = Request(
        _MAS_EXCHANGE_RATES_URL,
        data=urlencode(payload).encode("ascii"),
        headers={"Accept": "text/csv"},
        method="POST",
    )
    return _read_mas_response(download_request, timeout, expected_content_type="text/csv")


def _read_mas_response(request: Request, timeout: float, *, expected_content_type: str) -> bytes:
    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get_content_type()
            content = bytes(response.read())
    except (HTTPError, OSError, URLError) as error:
        raise ProviderError("MAS FX request failed") from error
    if content_type != expected_content_type:
        raise ProviderError("MAS FX response has an unexpected content type")
    if not content:
        raise ProviderError("MAS FX response is empty")
    return content


def _parse_mas_usd_sgd_csv(
    content: bytes, start_date: date, end_date: date
) -> tuple[tuple[date, Decimal], ...]:
    try:
        rows = tuple(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    except (UnicodeDecodeError, csv.Error) as error:
        raise ProviderError("MAS FX CSV is malformed") from error
    title_seen = False
    daily_seen = False
    header_seen = False
    current_year: int | None = None
    current_month: int | None = None
    observations: list[tuple[date, Decimal]] = []
    seen_dates: set[date] = set()
    for raw_row in rows:
        row = tuple(value.strip() for value in raw_row)
        if row == ("MAS: Financial Database - Exchange Rates",):
            title_seen = True
            continue
        if row == ("Exchange Rates (Daily)",):
            daily_seen = True
            continue
        if row == ("End of Period", "", "", "S$ Per Unit of US Dollar"):
            header_seen = True
            continue
        if not header_seen or not any(row) or row[0].startswith("*"):
            continue
        if len(row) != 4:
            raise ProviderError("MAS FX CSV contains an invalid rate row")
        year_text, month_text, day_text, rate_text = row
        try:
            if year_text:
                current_year = int(year_text)
            if month_text:
                current_month = _MAS_MONTHS[month_text]
            if current_year is None or current_month is None:
                raise ValueError("rate date is incomplete")
            session_date = date(current_year, current_month, int(day_text))
            rate = decimal(rate_text)
        except (KeyError, ValueError) as error:
            raise ProviderError("MAS FX CSV contains an invalid rate") from error
        if rate <= 0:
            raise ProviderError("MAS FX CSV contains a non-positive rate")
        if session_date in seen_dates:
            raise ProviderError("MAS FX CSV contains duplicate rate dates")
        seen_dates.add(session_date)
        if start_date <= session_date <= end_date:
            observations.append((session_date, rate))
    if not title_seen or not daily_seen or not header_seen:
        raise ProviderError("MAS FX CSV does not match the expected daily USD/SGD format")
    if not observations:
        raise ProviderError("MAS FX CSV contains no rates for the requested range")
    return tuple(observations)


def store_fx_rates(ledger: EncryptedLedger, rates: tuple[FxRate, ...]) -> int:
    inserted = 0
    with ledger.connection() as connection:
        _initialize(connection)
        for rate in rates:
            as_of_at = rate.as_of_at
            as_of_precision = rate.as_of_precision
            if as_of_at is None:
                raise ValueError("FX as-of time is required")
            if as_of_precision is None:
                raise ValueError("FX as-of precision is required")
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO fx_rates (
                    base_currency, quote_currency, session_date, rate, source_hash, as_of_at, provider_id,
                    as_of_precision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rate.base_currency.value,
                    rate.quote_currency.value,
                    rate.session_date.isoformat(),
                    str(rate.rate),
                    rate.source_hash,
                    as_of_at.isoformat(),
                    rate.provider_id,
                    as_of_precision.value,
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
                    datetime.fromisoformat(row["as_of_at"])
                    if row.get("as_of_at")
                    else None,
                    row.get("provider_id") or "csv",
                    FxAsOfPrecision.INSTANT if row.get("as_of_at") else FxAsOfPrecision.DATE,
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
                SELECT base_currency, quote_currency, MAX(as_of_at) AS as_of_at
                FROM fx_rates GROUP BY base_currency, quote_currency
            ) AS latest USING (base_currency, quote_currency, as_of_at)
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
            datetime.fromisoformat(row["as_of_at"]),
            row["provider_id"],
            FxAsOfPrecision(row["as_of_precision"]),
        )
        values[(rate.base_currency, rate.quote_currency)] = rate
    return values


def fx_rates_for_session(
    ledger: EncryptedLedger, session_date: date
) -> dict[tuple[Currency, Currency], FxRate]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT base_currency, quote_currency, session_date, rate, source_hash, as_of_at, provider_id,
                   as_of_precision
            FROM fx_rates
            WHERE session_date = ?
            ORDER BY base_currency, quote_currency, as_of_at DESC, source_hash ASC
            """,
            (session_date.isoformat(),),
        ).fetchall()
    values: dict[tuple[Currency, Currency], FxRate] = {}
    for row in rows:
        key = (Currency(row["base_currency"]), Currency(row["quote_currency"]))
        if key not in values:
            values[key] = FxRate(
                key[0],
                key[1],
                date.fromisoformat(row["session_date"]),
                Decimal(row["rate"]),
                row["source_hash"],
                datetime.fromisoformat(row["as_of_at"]),
                row["provider_id"],
                FxAsOfPrecision(row["as_of_precision"]),
            )
    return values


def store_instrument_masters(ledger: EncryptedLedger, instruments: tuple[InstrumentMaster, ...]) -> int:
    inserted = 0
    with ledger.connection() as connection:
        _initialize(connection)
        for instrument in instruments:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO instrument_master_versions (
                    canonical_id, exchange, market, currency, asset_class, provider_symbol, listing_status,
                    metadata_version, metadata_source_hash, etf_classification, classification_version,
                    margin_only, short_only, leveraged, inverse_product, recorded_at
                    , sector, sector_version, sector_source_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    instrument.canonical_id,
                    instrument.exchange,
                    instrument.market,
                    instrument.currency.value,
                    instrument.asset_class.value,
                    instrument.provider_symbol,
                    instrument.listing_status.value,
                    instrument.metadata_version,
                    instrument.metadata_source_hash,
                    instrument.etf_classification.value
                    if instrument.etf_classification is not None
                    else None,
                    instrument.classification_version,
                    instrument.margin_only,
                    instrument.short_only,
                    instrument.leveraged,
                    instrument.inverse,
                    datetime.now(UTC).isoformat(),
                    instrument.sector.value if instrument.sector is not None else None,
                    instrument.sector_version,
                    instrument.sector_source_hash,
                ),
            )
            inserted += cursor.rowcount
    return inserted


def instrument_master_versions(
    ledger: EncryptedLedger, canonical_id: str
) -> tuple[InstrumentMaster, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT * FROM instrument_master_versions
            WHERE canonical_id = ?
            ORDER BY rowid
            """,
            (canonical_id.strip().upper(),),
        ).fetchall()
    return tuple(_instrument_master_from_row(row) for row in rows)


def latest_instrument_masters(ledger: EncryptedLedger) -> dict[str, InstrumentMaster]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT * FROM instrument_master_versions
            WHERE rowid IN (
                SELECT MAX(rowid) FROM instrument_master_versions GROUP BY canonical_id
            )
            ORDER BY canonical_id
            """
        ).fetchall()
    return {row["canonical_id"]: _instrument_master_from_row(row) for row in rows}


def resolve_us_equity_or_etf(ledger: EncryptedLedger, identifier: str) -> InstrumentMaster:
    canonical_id = _canonical_us_identifier(identifier)
    instrument = latest_instrument_masters(ledger).get(canonical_id)
    if instrument is None:
        raise ProviderError("US symbol is not registered in the instrument master")
    if instrument.asset_class not in {AssetClass.EQUITY, AssetClass.ETF}:
        raise ProviderError("US symbol is not a supported equity or ETF")
    if instrument.provider_symbol != f"US.{instrument.instrument.symbol}":
        raise ProviderError("US symbol has an invalid Moomoo provider mapping")
    return instrument


def resolve_sg_equity_or_etf(ledger: EncryptedLedger, identifier: str) -> InstrumentMaster:
    canonical_id = _canonical_sg_identifier(identifier)
    instrument = latest_instrument_masters(ledger).get(canonical_id)
    if instrument is None:
        raise ProviderError("SG symbol is not registered in the instrument master")
    if instrument.asset_class not in {AssetClass.EQUITY, AssetClass.ETF}:
        raise ProviderError("SG symbol is not a supported equity or ETF")
    if instrument.provider_symbol != f"SG.{instrument.instrument.symbol}":
        raise ProviderError("SG symbol has an invalid Moomoo provider mapping")
    return instrument


def store_moomoo_instrument_eligibility(
    ledger: EncryptedLedger, evidence: tuple[MoomooInstrumentEligibility, ...]
) -> int:
    inserted = 0
    with ledger.connection() as connection:
        _initialize(connection)
        known = {
            row[0]
            for row in connection.execute("SELECT DISTINCT canonical_id FROM instrument_master_versions")
        }
        for item in evidence:
            if item.canonical_id not in known:
                raise ProviderError("Moomoo eligibility requires an instrument master record")
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO moomoo_instrument_eligibility (
                    canonical_id, account_key, observed_at, source_hash, available, cash_buy_eligible,
                    settled_cash_available
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.canonical_id,
                    item.account.key,
                    item.observed_at.isoformat(),
                    item.source_hash,
                    item.available,
                    item.cash_buy_eligible,
                    item.settled_cash_available,
                ),
            )
            inserted += cursor.rowcount
    return inserted


def latest_moomoo_instrument_eligibility(
    ledger: EncryptedLedger, account: Account
) -> dict[str, MoomooInstrumentEligibility]:
    if account.provider_id != "moomoo":
        raise ValueError("Moomoo eligibility requires a Moomoo account")
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT * FROM moomoo_instrument_eligibility
            WHERE account_key = ? AND rowid IN (
                SELECT MAX(rowid) FROM moomoo_instrument_eligibility
                WHERE account_key = ? GROUP BY canonical_id
            )
            ORDER BY canonical_id
            """,
            (account.key, account.key),
        ).fetchall()
    return {
        row["canonical_id"]: MoomooInstrumentEligibility(
            row["canonical_id"],
            account,
            datetime.fromisoformat(row["observed_at"]),
            row["source_hash"],
            bool(row["available"]),
            bool(row["cash_buy_eligible"]),
            bool(row["settled_cash_available"]),
        )
        for row in rows
    }


def is_recommendation_candidate(
    instrument: InstrumentMaster,
    evidence: MoomooInstrumentEligibility | None,
    selected_account: Account,
) -> bool:
    if selected_account.provider_id != "moomoo":
        raise ValueError("recommendation eligibility requires a Moomoo account")
    if evidence is None or evidence.canonical_id != instrument.canonical_id:
        return False
    if evidence.account != selected_account:
        return False
    return (
        instrument.asset_class is not AssetClass.INDEX
        and instrument.listing_status is ListingStatus.LISTED
        and not instrument.margin_only
        and not instrument.short_only
        and not instrument.leveraged
        and not instrument.inverse
        and evidence.available
        and evidence.cash_buy_eligible
        and evidence.settled_cash_available
    )


def convert_currency(
    amount: Decimal,
    source_currency: Currency,
    target_currency: Currency,
    rates: dict[tuple[Currency, Currency], FxRate],
) -> Decimal:
    resolution = resolve_fx_rate(source_currency, target_currency, rates)
    if resolution.rate is None:
        return decimal(amount)
    if resolution.inverted:
        return decimal(amount) / resolution.rate.rate
    return decimal(amount) * resolution.rate.rate


def resolve_fx_rate(
    source_currency: Currency,
    target_currency: Currency,
    rates: dict[tuple[Currency, Currency], FxRate],
) -> FxRateResolution:
    if not isinstance(source_currency, Currency) or not isinstance(target_currency, Currency):
        raise ValueError("FX currencies are required")
    if source_currency is target_currency:
        return FxRateResolution(source_currency, target_currency, None, Decimal("1"), False)
    direct = rates.get((source_currency, target_currency))
    if direct is not None:
        return FxRateResolution(source_currency, target_currency, direct, direct.rate, False)
    inverse = rates.get((target_currency, source_currency))
    if inverse is not None:
        return FxRateResolution(source_currency, target_currency, inverse, Decimal("1") / inverse.rate, True)
    raise ProviderError(
        f"missing FX rate:{source_currency.value}:{target_currency.value}"
    )


def fx_rate_freshness(
    rate: FxRate,
    *,
    as_of: datetime,
    maximum_age: timedelta,
) -> FxRateFreshness:
    if as_of.tzinfo is None:
        raise ValueError("FX freshness time must be timezone-aware")
    if maximum_age < timedelta(0):
        raise ValueError("maximum FX age must be non-negative")
    observed_at = as_of.astimezone(UTC)
    rate_as_of = rate.as_of_at
    if rate_as_of is None:
        raise ValueError("FX as-of time is required")
    age = observed_at - rate_as_of
    if age < timedelta(0):
        raise ProviderError("FX rate is after requested time")
    return FxRateFreshness(rate, observed_at, age, age > maximum_age)


def _instrument_master_from_row(row: sqlite3.Row) -> InstrumentMaster:
    classification = row["etf_classification"]
    return InstrumentMaster(
        row["canonical_id"],
        row["exchange"],
        row["market"],
        Currency(row["currency"]),
        AssetClass(row["asset_class"]),
        row["provider_symbol"],
        ListingStatus(row["listing_status"]),
        row["metadata_version"],
        row["metadata_source_hash"],
        ETFClassification(classification) if classification is not None else None,
        row["classification_version"],
        bool(row["margin_only"]),
        bool(row["short_only"]),
        bool(row["leveraged"]),
        bool(row["inverse_product"]),
        GICSSector(row["sector"]) if row["sector"] is not None else None,
        row["sector_version"],
        row["sector_source_hash"],
    )


def _canonical_us_identifier(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("US symbol is required")
    identifier = value.strip().upper()
    if identifier.startswith(("SG:", "SG.")):
        raise ValueError("US symbol must not identify another market")
    if identifier.startswith("US:") or identifier.startswith("US."):
        identifier = identifier[3:]
    if not _US_TICKER.fullmatch(identifier):
        raise ValueError("US symbol format is invalid")
    return f"US:{identifier}"


def _canonical_sg_identifier(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("SG symbol is required")
    identifier = value.strip().upper()
    if identifier.startswith(("US:", "US.")):
        raise ValueError("SG symbol must not identify another market")
    if identifier.startswith("SG:") or identifier.startswith("SG."):
        identifier = identifier[3:]
    if not _SG_TICKER.fullmatch(identifier):
        raise ValueError("SG symbol format is invalid")
    return f"SG:{identifier}"


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
    ohlc_fields = {"open", "high", "low"}
    if ohlc_fields & set(rows.fieldnames) and not ohlc_fields <= set(rows.fieldnames):
        raise ProviderError("price CSV OHLC requires open,high,low")
    has_ohlc = ohlc_fields <= set(rows.fieldnames)
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
                    decimal(row["open"] or "") if has_ohlc else None,
                    decimal(row["high"] or "") if has_ohlc else None,
                    decimal(row["low"] or "") if has_ohlc else None,
                )
            )
        except (KeyError, ValueError) as error:
            raise ProviderError("price CSV contains invalid data") from error
    return store_daily_prices(ledger, prices)
