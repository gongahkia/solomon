from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from stonks_cli.accounting import fifo_lots, unrealized_pnl
from stonks_cli.analytics import (
    allocations_by_currency,
    cash_by_currency,
    concentration_hhi,
    convert_values_to_currency,
    market_values_by_currency,
    maximum_drawdown,
    money_weighted_return,
    portfolio_health,
    time_weighted_return,
)
from stonks_cli.market_data import FxRate
from stonks_cli.types import (
    Account,
    Currency,
    EventKind,
    Instrument,
    LedgerEvent,
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
