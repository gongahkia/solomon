from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from stonks_cli.accounting import fifo_lots, unrealized_pnl
from stonks_cli.analytics import (
    allocations_by_currency,
    asset_class_allocation,
    asset_class_allocations_by_currency,
    benchmark_relative_return,
    cash_by_currency,
    concentration_hhi,
    convert_values_to_currency,
    dividend_and_fee_attribution,
    market_values_by_currency,
    maximum_drawdown,
    money_weighted_return,
    portfolio_health,
    portfolio_return_attribution,
    sector_concentration,
    sector_concentrations_by_currency,
    time_weighted_return,
)
from stonks_cli.errors import ProviderError
from stonks_cli.market_data import FxRate
from stonks_cli.types import (
    Account,
    AssetClass,
    Currency,
    ETFClassification,
    EventKind,
    GICSSector,
    Instrument,
    InstrumentMaster,
    LedgerEvent,
    ListingStatus,
    SourceProvenance,
)


def _buy(symbol: str, currency: Currency, quantity: str) -> LedgerEvent:
    return LedgerEvent(
        fingerprint=f"buy-{symbol}",
        source=SourceProvenance("test", "a" * 64, f"buy-{symbol}"),
        account=Account("test", "main"),
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        kind=EventKind.BUY,
        currency=currency,
        amount=Decimal("1"),
        quantity=Decimal(quantity),
        instrument=Instrument(symbol, "US" if currency is Currency.USD else "SG", currency),
    )


def test_analytics_does_not_combine_unconverted_currencies() -> None:
    events = [_buy("SPY", Currency.USD, "2"), _buy("D05", Currency.SGD, "3")]
    prices = {"US:SPY": Decimal("100"), "SG:D05": Decimal("30")}

    values = market_values_by_currency(events, prices)

    assert values[Currency.USD][("test:main", "US:SPY")] == Decimal("200")
    assert values[Currency.SGD][("test:main", "SG:D05")] == Decimal("90")
    assert allocations_by_currency(events, prices)[Currency.USD] == {
        ("test:main", "US:SPY"): Decimal("1")
    }
    assert convert_values_to_currency(
        values,
        Currency.SGD,
        {(Currency.USD, Currency.SGD): FxRate(Currency.USD, Currency.SGD, datetime(2026, 1, 1).date(), Decimal("1.35"), "a" * 64)},
    )[("test:main", "US:SPY")] == Decimal("270")


def test_analytics_reports_returns_drawdown_concentration_and_missing_prices() -> None:
    events = [_buy("SPY", Currency.USD, "2")]

    assert concentration_hhi({("main", "US:SPY"): Decimal("100")}) == Decimal("1")
    assert maximum_drawdown((Decimal("100"), Decimal("80"), Decimal("90"))) == Decimal("-0.2")
    assert time_weighted_return(((Decimal("100"), Decimal("0"), Decimal("110")),)) == Decimal(
        "0.1"
    )
    assert benchmark_relative_return(Decimal("0.1"), Decimal("0.08")) == Decimal("0.02")
    health = portfolio_health(events, {}, stale_instruments=("US:SPY",))
    assert health.missing_prices == ("US:SPY",)
    assert health.stale_instruments == ("US:SPY",)


def test_analytics_calculates_unrealized_money_weighted_and_currency_exposure() -> None:
    buy = _buy("SPY", Currency.USD, "2")
    deposit = LedgerEvent(
        fingerprint="deposit",
        source=SourceProvenance("test", "b" * 64, "deposit"),
        account=buy.account,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        kind=EventKind.CASH_DEPOSIT,
        currency=Currency.USD,
        amount=Decimal("100"),
    )
    lots, _ = fifo_lots([buy])
    annualized = money_weighted_return(
        [
            (datetime(2026, 1, 1, tzinfo=UTC), Decimal("-100")),
            (datetime(2027, 1, 1, tzinfo=UTC), Decimal("110")),
        ]
    )

    assert unrealized_pnl(lots, {"US:SPY": Decimal("3")}) == Decimal("5")
    assert Decimal("0.09") < annualized < Decimal("0.11")
    assert cash_by_currency([deposit]) == {Currency.USD: Decimal("100")}


def test_asset_class_allocation_uses_versioned_instrument_classifications() -> None:
    masters = {
        "US:SPY": InstrumentMaster(
            "US:SPY",
            "ARCA",
            "US",
            Currency.USD,
            AssetClass.ETF,
            "US.SPY",
            ListingStatus.LISTED,
            "issuer-2026-01",
            "a" * 64,
            ETFClassification.BROAD_DIVERSIFIED,
            "issuer-2026-01",
        ),
        "SG:C6L": InstrumentMaster(
            "SG:C6L",
            "SGX",
            "SG",
            Currency.SGD,
            AssetClass.EQUITY,
            "SG.C6L",
            ListingStatus.LISTED,
            "sgx-2026-01",
            "b" * 64,
        ),
    }
    values = {
        ("test:main", "US:SPY"): Decimal("200"),
        ("test:main", "SG:C6L"): Decimal("50"),
    }

    assert asset_class_allocation(values, masters) == {
        AssetClass.ETF: Decimal("0.8"),
        AssetClass.EQUITY: Decimal("0.2"),
    }
    assert asset_class_allocations_by_currency(
        {
            Currency.USD: {("test:main", "US:SPY"): Decimal("200")},
            Currency.SGD: {("test:main", "SG:C6L"): Decimal("50")},
        },
        masters,
    ) == {
        Currency.USD: {AssetClass.ETF: Decimal("1")},
        Currency.SGD: {AssetClass.EQUITY: Decimal("1")},
    }
    with pytest.raises(ProviderError, match="unavailable:US:UNKNOWN"):
        asset_class_allocation({("test:main", "US:UNKNOWN"): Decimal("1")}, masters)
    with pytest.raises(ValueError, match="negative"):
        asset_class_allocation({("test:main", "US:SPY"): Decimal("-1")}, masters)


def test_sector_concentration_requires_explicit_versioned_sector_metadata() -> None:
    masters = {
        "US:NVDA": InstrumentMaster(
            "US:NVDA",
            "NASDAQ",
            "US",
            Currency.USD,
            AssetClass.EQUITY,
            "US.NVDA",
            ListingStatus.LISTED,
            "issuer-2026-01",
            "a" * 64,
            sector=GICSSector.INFORMATION_TECHNOLOGY,
            sector_version="gics-2025",
            sector_source_hash="b" * 64,
        ),
        "SG:C6L": InstrumentMaster(
            "SG:C6L",
            "SGX",
            "SG",
            Currency.SGD,
            AssetClass.EQUITY,
            "SG.C6L",
            ListingStatus.LISTED,
            "sgx-2026-01",
            "c" * 64,
            sector=GICSSector.INDUSTRIALS,
            sector_version="gics-2025",
            sector_source_hash="d" * 64,
        ),
    }
    values = {
        ("test:main", "US:NVDA"): Decimal("90"),
        ("test:main", "SG:C6L"): Decimal("10"),
    }

    concentration = sector_concentration(values, masters)

    assert concentration.allocation == {
        GICSSector.INDUSTRIALS: Decimal("0.1"),
        GICSSector.INFORMATION_TECHNOLOGY: Decimal("0.9"),
    }
    assert concentration.hhi == Decimal("0.82")
    assert sector_concentrations_by_currency(
        {Currency.USD: {("test:main", "US:NVDA"): Decimal("90")}}, masters
    )[Currency.USD].hhi == Decimal("1")
    with pytest.raises(ProviderError, match="sector is unavailable:US:UNKNOWN"):
        sector_concentration({("test:main", "US:UNKNOWN"): Decimal("1")}, masters)
    with pytest.raises(ValueError, match="sector metadata"):
        InstrumentMaster(
            "US:NVDA",
            "NASDAQ",
            "US",
            Currency.USD,
            AssetClass.EQUITY,
            "US.NVDA",
            ListingStatus.LISTED,
            "issuer-2026-01",
            "e" * 64,
            sector=GICSSector.INFORMATION_TECHNOLOGY,
        )


def test_dividend_and_fee_attribution_preserves_currency_and_fee_origin() -> None:
    buy = _buy("SPY", Currency.USD, "1")
    fee = LedgerEvent(
        fingerprint="fee",
        source=SourceProvenance("test", "b" * 64, "fee"),
        account=buy.account,
        occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
        kind=EventKind.FEE,
        currency=Currency.USD,
        amount=Decimal("2"),
    )
    dividend = LedgerEvent(
        fingerprint="dividend",
        source=SourceProvenance("test", "c" * 64, "dividend"),
        account=buy.account,
        occurred_at=datetime(2026, 1, 3, tzinfo=UTC),
        kind=EventKind.DIVIDEND,
        currency=Currency.USD,
        amount=Decimal("5"),
        instrument=buy.instrument,
    )
    trade_with_fee = LedgerEvent(
        fingerprint="buy-fee",
        source=SourceProvenance("test", "d" * 64, "buy-fee"),
        account=buy.account,
        occurred_at=datetime(2026, 1, 4, tzinfo=UTC),
        kind=EventKind.BUY,
        currency=Currency.USD,
        amount=Decimal("10"),
        quantity=Decimal("1"),
        instrument=buy.instrument,
        fee=Decimal("1"),
    )

    attribution = dividend_and_fee_attribution([buy, fee, dividend, trade_with_fee])[Currency.USD]

    assert attribution.dividends == Decimal("5")
    assert attribution.standalone_fees == Decimal("2")
    assert attribution.trade_fees == Decimal("1")
    assert attribution.fees == Decimal("3")
    assert attribution.net_return_contribution == Decimal("2")


def test_portfolio_return_attribution_reconciles_market_income_and_fees() -> None:
    attribution = portfolio_return_attribution(
        opening_value=Decimal("100"),
        closing_value=Decimal("112"),
        external_cash_flow=Decimal("5"),
        market_gain=Decimal("5"),
        dividends=Decimal("5"),
        fees=Decimal("3"),
    )

    assert attribution.total_return == Decimal("0.07")
    assert attribution.market_return == Decimal("0.05")
    assert attribution.dividend_return == Decimal("0.05")
    assert attribution.fee_return == Decimal("-0.03")
    with pytest.raises(ValueError, match="does not reconcile"):
        portfolio_return_attribution(
            opening_value=Decimal("100"),
            closing_value=Decimal("112"),
            external_cash_flow=Decimal("5"),
            market_gain=Decimal("6"),
            dividends=Decimal("5"),
            fees=Decimal("2"),
        )
