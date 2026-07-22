from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from stonks_cli.errors import ProviderError
from stonks_cli.market_data import FxRate, convert_currency
from stonks_cli.types import (
    AssetClass,
    Currency,
    EventKind,
    GICSSector,
    InstrumentMaster,
    LedgerEvent,
)


def market_values(
    positions: dict[tuple[str, str], Decimal], prices: dict[str, Decimal]
) -> dict[tuple[str, str], Decimal]:
    values: dict[tuple[str, str], Decimal] = {}
    for key, quantity in positions.items():
        _, instrument = key
        if instrument not in prices:
            continue
        values[key] = quantity * prices[instrument]
    return values


def allocation(values: dict[tuple[str, str], Decimal]) -> dict[tuple[str, str], Decimal]:
    total = sum(values.values(), Decimal("0"))
    return {} if total == 0 else {key: value / total for key, value in values.items()}


def market_values_by_currency(
    events: list[LedgerEvent], prices: dict[str, Decimal]
) -> dict[Currency, dict[tuple[str, str], Decimal]]:
    currencies: dict[tuple[str, str], Currency] = {}
    for event in events:
        if event.instrument is not None:
            currencies[(event.account_id, event.instrument.key)] = event.instrument.currency
    from stonks_cli.ledger import positions

    grouped: dict[Currency, dict[tuple[str, str], Decimal]] = defaultdict(dict)
    for key, value in market_values(positions(events), prices).items():
        try:
            grouped[currencies[key]][key] = value
        except KeyError as error:
            raise ValueError(f"position currency is unknown:{key[1]}") from error
    return dict(grouped)


def allocations_by_currency(
    events: list[LedgerEvent], prices: dict[str, Decimal]
) -> dict[Currency, dict[tuple[str, str], Decimal]]:
    return {
        currency: allocation(values)
        for currency, values in market_values_by_currency(events, prices).items()
    }


def asset_class_allocation(
    values: Mapping[tuple[str, str], Decimal],
    instrument_masters: Mapping[str, InstrumentMaster],
) -> dict[AssetClass, Decimal]:
    totals: dict[AssetClass, Decimal] = defaultdict(Decimal)
    for (_, instrument_key), value in values.items():
        if value < 0:
            raise ValueError("asset-class allocation cannot include negative values")
        if value == 0:
            continue
        instrument = instrument_masters.get(instrument_key)
        if instrument is None:
            raise ProviderError(f"asset class is unavailable:{instrument_key}")
        totals[instrument.asset_class] += value
    total = sum(totals.values(), Decimal("0"))
    return {} if total == 0 else {asset_class: value / total for asset_class, value in totals.items()}


def asset_class_allocations_by_currency(
    values_by_currency: Mapping[Currency, Mapping[tuple[str, str], Decimal]],
    instrument_masters: Mapping[str, InstrumentMaster],
) -> dict[Currency, dict[AssetClass, Decimal]]:
    return {
        currency: asset_class_allocation(values, instrument_masters)
        for currency, values in values_by_currency.items()
    }


@dataclass(frozen=True)
class SectorConcentration:
    allocation: dict[GICSSector, Decimal]
    hhi: Decimal


def sector_concentration(
    values: Mapping[tuple[str, str], Decimal],
    instrument_masters: Mapping[str, InstrumentMaster],
) -> SectorConcentration:
    totals: dict[GICSSector, Decimal] = defaultdict(Decimal)
    for (_, instrument_key), value in values.items():
        if value < 0:
            raise ValueError("sector concentration cannot include negative values")
        if value == 0:
            continue
        instrument = instrument_masters.get(instrument_key)
        if instrument is None or instrument.sector is None:
            raise ProviderError(f"sector is unavailable:{instrument_key}")
        totals[instrument.sector] += value
    total = sum(totals.values(), Decimal("0"))
    allocation = (
        {}
        if total == 0
        else {sector: value / total for sector, value in sorted(totals.items())}
    )
    return SectorConcentration(allocation, sum((value * value for value in allocation.values()), Decimal("0")))


def sector_concentrations_by_currency(
    values_by_currency: Mapping[Currency, Mapping[tuple[str, str], Decimal]],
    instrument_masters: Mapping[str, InstrumentMaster],
) -> dict[Currency, SectorConcentration]:
    return {
        currency: sector_concentration(values, instrument_masters)
        for currency, values in values_by_currency.items()
    }


@dataclass(frozen=True)
class DividendAndFeeAttribution:
    dividends: Decimal
    standalone_fees: Decimal
    trade_fees: Decimal

    @property
    def fees(self) -> Decimal:
        return self.standalone_fees + self.trade_fees

    @property
    def net_return_contribution(self) -> Decimal:
        return self.dividends - self.fees


def dividend_and_fee_attribution(
    events: list[LedgerEvent],
) -> dict[Currency, DividendAndFeeAttribution]:
    from stonks_cli.ledger import effective_events

    values: dict[Currency, list[Decimal]] = defaultdict(
        lambda: [Decimal("0"), Decimal("0"), Decimal("0")]
    )
    for event in effective_events(events):
        entry = values[event.currency]
        if event.kind is EventKind.DIVIDEND:
            entry[0] += event.amount
        elif event.kind is EventKind.FEE:
            entry[1] += event.amount
        elif event.kind in {EventKind.BUY, EventKind.SELL}:
            entry[2] += event.fee
    return {
        currency: DividendAndFeeAttribution(*amounts)
        for currency, amounts in sorted(values.items(), key=lambda item: item[0].value)
    }


@dataclass(frozen=True)
class PortfolioReturnAttribution:
    total_return: Decimal
    market_return: Decimal
    dividend_return: Decimal
    fee_return: Decimal
    opening_value: Decimal
    closing_value: Decimal
    external_cash_flow: Decimal
    market_gain: Decimal
    dividends: Decimal
    fees: Decimal


def portfolio_return_attribution(
    *,
    opening_value: Decimal,
    closing_value: Decimal,
    external_cash_flow: Decimal,
    market_gain: Decimal,
    dividends: Decimal,
    fees: Decimal,
) -> PortfolioReturnAttribution:
    if opening_value <= 0 or closing_value < 0:
        raise ValueError("return attribution opening and closing values are invalid")
    if dividends < 0 or fees < 0:
        raise ValueError("return attribution dividends and fees must be non-negative")
    net_gain = closing_value - opening_value - external_cash_flow
    attributed_gain = market_gain + dividends - fees
    if net_gain != attributed_gain:
        raise ValueError("return attribution does not reconcile")
    return PortfolioReturnAttribution(
        net_gain / opening_value,
        market_gain / opening_value,
        dividends / opening_value,
        -fees / opening_value,
        opening_value,
        closing_value,
        external_cash_flow,
        market_gain,
        dividends,
        fees,
    )


def convert_values_to_currency(
    values_by_currency: dict[Currency, dict[tuple[str, str], Decimal]],
    target_currency: Currency,
    rates: dict[tuple[Currency, Currency], FxRate],
) -> dict[tuple[str, str], Decimal]:
    converted: dict[tuple[str, str], Decimal] = {}
    for currency, values in values_by_currency.items():
        for key, value in values.items():
            converted[key] = convert_currency(value, currency, target_currency, rates)
    return converted


def concentration_hhi(values: dict[tuple[str, str], Decimal]) -> Decimal:
    return sum((weight * weight for weight in allocation(values).values()), Decimal("0"))


def maximum_drawdown(values: tuple[Decimal, ...]) -> Decimal:
    if not values or any(value <= 0 for value in values):
        raise ValueError("drawdown values must be non-empty and positive")
    peak = values[0]
    drawdown = Decimal("0")
    for value in values:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - Decimal("1"))
    return drawdown


def time_weighted_return(periods: tuple[tuple[Decimal, Decimal, Decimal], ...]) -> Decimal:
    """Chain returns from (opening value, external cash flow, closing value) periods."""
    if not periods:
        raise ValueError("at least one return period is required")
    result = Decimal("1")
    for opening, external_flow, closing in periods:
        if opening <= 0 or closing < 0:
            raise ValueError("return period values are invalid")
        result *= (closing - external_flow) / opening
    return result - Decimal("1")


def benchmark_relative_return(portfolio_return: Decimal, benchmark_return: Decimal) -> Decimal:
    return portfolio_return - benchmark_return


@dataclass(frozen=True)
class PortfolioHealth:
    concentration_hhi: Decimal | None
    stale_instruments: tuple[str, ...]
    missing_prices: tuple[str, ...]


def portfolio_health(
    events: list[LedgerEvent],
    prices: dict[str, Decimal],
    *,
    stale_instruments: tuple[str, ...] = (),
) -> PortfolioHealth:
    from stonks_cli.ledger import positions

    held = positions(events)
    missing = tuple(sorted(key[1] for key in held if key[1] not in prices))
    values = market_values(held, prices)
    return PortfolioHealth(
        concentration_hhi(values) if values else None,
        tuple(sorted(set(stale_instruments))),
        missing,
    )


def cash_by_currency(events: list[LedgerEvent]) -> dict[Currency, Decimal]:
    values: dict[Currency, Decimal] = defaultdict(Decimal)
    from stonks_cli.ledger import cash_balances

    for (_, currency), amount in cash_balances(events).items():
        values[currency] += amount
    return dict(values)


def money_weighted_return(
    cashflows: list[tuple[datetime, Decimal]], *, precision: Decimal = Decimal("0.000001")
) -> Decimal:
    if (
        len(cashflows) < 2
        or not any(amount < 0 for _, amount in cashflows)
        or not any(amount > 0 for _, amount in cashflows)
    ):
        raise ValueError("cashflows require positive and negative values")
    start = min(at for at, _ in cashflows)

    def npv(rate: Decimal) -> Decimal:
        return sum(
            (
                amount / ((Decimal("1") + rate) ** Decimal((at - start).days / 365.25))
                for at, amount in cashflows
            ),
            Decimal("0"),
        )

    low, high = Decimal("-0.9999"), Decimal("10")
    low_value, high_value = npv(low), npv(high)
    if low_value * high_value > 0:
        raise ValueError("cashflows do not bracket a money-weighted return")
    for _ in range(128):
        middle = (low + high) / 2
        value = npv(middle)
        if abs(value) <= precision:
            return middle
        if low_value * value <= 0:
            high, high_value = middle, value
        else:
            low, low_value = middle, value
    return (low + high) / 2
