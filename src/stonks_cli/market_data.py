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
from stonks_cli.types import (
    Account,
    AssetClass,
    Currency,
    ETFClassification,
    Instrument,
    InstrumentMaster,
    ListingStatus,
    MoomooInstrumentEligibility,
    decimal,
)


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
            recorded_at TEXT NOT NULL,
            PRIMARY KEY(canonical_id, metadata_version, metadata_source_hash)
        )
        """
    )
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
