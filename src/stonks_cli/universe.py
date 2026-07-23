from __future__ import annotations

import csv
import io
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from stonks_cli.config import EODUniverseSettings
from stonks_cli.errors import ProviderError
from stonks_cli.market_data import DailyPrice, FxRate, QuoteSnapshot, QuoteStatus, resolve_fx_rate
from stonks_cli.storage import EncryptedLedger
from stonks_cli.types import (
    Account,
    AssetClass,
    Currency,
    InstrumentMaster,
    ListingStatus,
    MoomooInstrumentEligibility,
)

_HASH = re.compile(r"^[0-9a-f]{64}$")
_PROVIDER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class DailyLiquidity:
    canonical_id: str
    session_date: date
    traded_value: Decimal
    currency: Currency
    source_hash: str
    as_of_at: datetime
    provider_id: str

    def __post_init__(self) -> None:
        canonical_id = self.canonical_id.strip().upper()
        market, separator, symbol = canonical_id.partition(":")
        if not separator or ":" in symbol or market not in {"US", "SG"}:
            raise ValueError("daily liquidity canonical identifier must use US or SG market")
        if not isinstance(self.session_date, date) or not isinstance(self.currency, Currency):
            raise ValueError("daily liquidity session date and currency are required")
        try:
            traded_value = Decimal(self.traded_value)
        except (InvalidOperation, ValueError) as error:
            raise ValueError("daily liquidity traded value must be decimal") from error
        if not traded_value.is_finite() or traded_value < 0:
            raise ValueError("daily liquidity traded value must be non-negative")
        if self.as_of_at.tzinfo is None:
            raise ValueError("daily liquidity as-of time must be timezone-aware")
        as_of_at = self.as_of_at.astimezone(UTC)
        if as_of_at.date() != self.session_date:
            raise ValueError("daily liquidity as-of time must match session date")
        source_hash = self.source_hash.lower()
        provider_id = self.provider_id.strip().lower()
        if not _HASH.fullmatch(source_hash) or not _PROVIDER.fullmatch(provider_id):
            raise ValueError("daily liquidity source provenance is invalid")
        object.__setattr__(self, "canonical_id", canonical_id)
        object.__setattr__(self, "traded_value", traded_value)
        object.__setattr__(self, "as_of_at", as_of_at)
        object.__setattr__(self, "source_hash", source_hash)
        object.__setattr__(self, "provider_id", provider_id)


@dataclass(frozen=True)
class EODUniverseDecision:
    canonical_id: str
    instrument: InstrumentMaster
    eligibility: MoomooInstrumentEligibility | None
    included: bool
    reasons: tuple[str, ...]
    price: DailyPrice | None
    liquidity: tuple[DailyLiquidity, ...]
    quote: QuoteSnapshot | None
    fx_rates: tuple[FxRate, ...]
    configuration_version: int


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS eod_daily_liquidity (
            canonical_id TEXT NOT NULL,
            session_date TEXT NOT NULL,
            traded_value TEXT NOT NULL,
            currency TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            as_of_at TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            UNIQUE(canonical_id, session_date, source_hash)
        )
        """
    )


def store_daily_liquidity(ledger: EncryptedLedger, values: tuple[DailyLiquidity, ...]) -> int:
    inserted = 0
    with ledger.connection() as connection:
        _initialize(connection)
        for value in values:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO eod_daily_liquidity (
                    canonical_id, session_date, traded_value, currency, source_hash, as_of_at, provider_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    value.canonical_id,
                    value.session_date.isoformat(),
                    str(value.traded_value),
                    value.currency.value,
                    value.source_hash,
                    value.as_of_at.isoformat(),
                    value.provider_id,
                ),
            )
            inserted += cursor.rowcount
    return inserted


def import_daily_liquidity_csv(ledger: EncryptedLedger, path: Path) -> int:
    content = path.read_bytes()
    source_hash = ledger.archive_source(content)
    try:
        rows = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    except UnicodeDecodeError as error:
        raise ProviderError("daily liquidity CSV must be UTF-8") from error
    required = {"date", "identifier", "currency", "traded_value"}
    if rows.fieldnames is None or not required <= set(rows.fieldnames):
        raise ProviderError("daily liquidity CSV requires date,identifier,currency,traded_value")
    values: list[DailyLiquidity] = []
    for row in rows:
        try:
            values.append(
                DailyLiquidity(
                    row["identifier"] or "",
                    date.fromisoformat(row["date"] or ""),
                    Decimal(row["traded_value"] or ""),
                    Currency((row["currency"] or "").upper()),
                    source_hash,
                    datetime.fromisoformat(row["as_of_at"])
                    if row.get("as_of_at")
                    else datetime.combine(date.fromisoformat(row["date"] or ""), datetime.min.time(), UTC),
                    row.get("provider_id") or "csv",
                )
            )
        except (KeyError, ValueError, InvalidOperation) as error:
            raise ProviderError("daily liquidity CSV contains invalid data") from error
    return store_daily_liquidity(ledger, tuple(values))


def latest_daily_liquidity(ledger: EncryptedLedger) -> dict[str, tuple[DailyLiquidity, ...]]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT canonical_id, session_date, traded_value, currency, source_hash, as_of_at, provider_id
            FROM eod_daily_liquidity
            ORDER BY canonical_id, session_date, as_of_at DESC, source_hash ASC
            """
        ).fetchall()
    values: dict[str, list[DailyLiquidity]] = {}
    seen: set[tuple[str, date]] = set()
    for row in rows:
        session_date = date.fromisoformat(row["session_date"])
        key = (row["canonical_id"], session_date)
        if key in seen:
            continue
        seen.add(key)
        values.setdefault(row["canonical_id"], []).append(
            DailyLiquidity(
                row["canonical_id"],
                session_date,
                Decimal(row["traded_value"]),
                Currency(row["currency"]),
                row["source_hash"],
                datetime.fromisoformat(row["as_of_at"]),
                row["provider_id"],
            )
        )
    return {identifier: tuple(sorted(items, key=lambda item: item.session_date)) for identifier, items in values.items()}


def evaluate_eod_universe(
    instruments: tuple[InstrumentMaster, ...],
    eligibility: dict[str, MoomooInstrumentEligibility],
    selected_account: Account,
    prices: dict[str, DailyPrice],
    liquidity: dict[str, tuple[DailyLiquidity, ...]],
    quotes: dict[str, QuoteSnapshot],
    fx_rates_by_session: dict[date, dict[tuple[Currency, Currency], FxRate]],
    settings: EODUniverseSettings,
) -> tuple[EODUniverseDecision, ...]:
    if selected_account.provider_id != "moomoo":
        raise ValueError("universe evaluation requires a Moomoo account")
    return tuple(
        _evaluate_instrument(
            instrument,
            eligibility.get(instrument.canonical_id),
            selected_account,
            prices.get(instrument.canonical_id),
            liquidity.get(instrument.canonical_id, ()),
            quotes.get(instrument.canonical_id),
            fx_rates_by_session,
            settings,
        )
        for instrument in sorted(instruments, key=lambda item: item.canonical_id)
    )


def _evaluate_instrument(
    instrument: InstrumentMaster,
    eligibility: MoomooInstrumentEligibility | None,
    selected_account: Account,
    price: DailyPrice | None,
    liquidity: tuple[DailyLiquidity, ...],
    quote: QuoteSnapshot | None,
    fx_rates_by_session: dict[date, dict[tuple[Currency, Currency], FxRate]],
    settings: EODUniverseSettings,
) -> EODUniverseDecision:
    reasons: list[str] = []
    if instrument.asset_class not in {AssetClass.EQUITY, AssetClass.ETF, AssetClass.REIT}:
        reasons.append("unsupported_asset_class")
    if instrument.listing_status is not ListingStatus.LISTED:
        reasons.append("not_listed")
    if instrument.margin_only or instrument.short_only or instrument.leveraged or instrument.inverse:
        reasons.append("restricted_instrument")
    if (
        eligibility is None
        or eligibility.account != selected_account
        or eligibility.canonical_id != instrument.canonical_id
    ):
        reasons.append("missing_cash_eligibility")
    elif not (eligibility.available and eligibility.cash_buy_eligible and eligibility.settled_cash_available):
        reasons.append("cash_buy_ineligible")
    _apply_price_filter(reasons, instrument, price, fx_rates_by_session, settings)
    _apply_liquidity_filter(reasons, instrument, liquidity, fx_rates_by_session, settings)
    _apply_spread_filter(reasons, instrument, quote, settings)
    sessions = {item.session_date for item in liquidity}
    if price is not None:
        sessions.add(price.session_date)
    fx_rates = tuple(
        sorted(
            (
                rate
                for session in sessions
                for rate in fx_rates_by_session.get(session, {}).values()
            ),
            key=lambda rate: (
                rate.session_date,
                rate.base_currency.value,
                rate.quote_currency.value,
                rate.as_of_at,
                rate.source_hash,
            ),
        )
    )
    return EODUniverseDecision(
        instrument.canonical_id,
        instrument,
        eligibility,
        not reasons,
        tuple(reasons),
        price,
        tuple(sorted(liquidity, key=lambda item: item.session_date)),
        quote,
        fx_rates,
        settings.version,
    )


def _apply_price_filter(
    reasons: list[str],
    instrument: InstrumentMaster,
    price: DailyPrice | None,
    fx_rates_by_session: dict[date, dict[tuple[Currency, Currency], FxRate]],
    settings: EODUniverseSettings,
) -> None:
    if instrument.asset_class is not AssetClass.EQUITY:
        return
    if price is None or price.instrument.key != instrument.canonical_id:
        reasons.append("missing_daily_price")
        return
    try:
        resolution = resolve_fx_rate(price.instrument.currency, Currency.USD, fx_rates_by_session[price.session_date])
    except (KeyError, ValueError):
        reasons.append("missing_price_fx")
        return
    if price.close * resolution.conversion_rate < Decimal(settings.individual_price_floor_usd):
        reasons.append("below_individual_price_floor")


def _apply_liquidity_filter(
    reasons: list[str],
    instrument: InstrumentMaster,
    liquidity: tuple[DailyLiquidity, ...],
    fx_rates_by_session: dict[date, dict[tuple[Currency, Currency], FxRate]],
    settings: EODUniverseSettings,
) -> None:
    observations = sorted(liquidity, key=lambda item: item.session_date, reverse=True)[
        : settings.liquidity_window_sessions
    ]
    if len({item.session_date for item in observations}) < settings.liquidity_minimum_sessions:
        reasons.append("insufficient_liquidity_sessions")
        return
    values: list[Decimal] = []
    for observation in observations:
        if observation.canonical_id != instrument.canonical_id:
            reasons.append("invalid_liquidity_identifier")
            return
        try:
            resolution = resolve_fx_rate(
                observation.currency, Currency.SGD, fx_rates_by_session[observation.session_date]
            )
        except (KeyError, ValueError):
            reasons.append("missing_liquidity_fx")
            return
        values.append(observation.traded_value * resolution.conversion_rate)
    if sum(values, Decimal("0")) / len(values) < Decimal(settings.liquidity_floor_sgd):
        reasons.append("below_liquidity_floor")


def _apply_spread_filter(
    reasons: list[str],
    instrument: InstrumentMaster,
    quote: QuoteSnapshot | None,
    settings: EODUniverseSettings,
) -> None:
    if quote is None or quote.instrument.key != instrument.canonical_id:
        reasons.append("missing_quote")
        return
    if quote.status is not QuoteStatus.AVAILABLE or quote.current_price is None:
        reasons.append("quote_not_fresh_entitled")
        return
    if quote.market_session.value == "unknown" or quote.order_book_as_of is None:
        reasons.append("missing_order_book_freshness")
        return
    if quote.midpoint is None or quote.spread is None:
        reasons.append("missing_bid_ask_spread")
        return
    if quote.spread / quote.midpoint > Decimal(settings.maximum_spread_fraction):
        reasons.append("excessive_spread")
