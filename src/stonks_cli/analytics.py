from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from stonks_cli.types import Currency, LedgerEvent


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
