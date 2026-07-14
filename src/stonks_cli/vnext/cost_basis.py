from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from stonks_cli.vnext.transactions_import import PortfolioTransaction, PortfolioTransactionSide


@dataclass(frozen=True)
class CostBasis:
    account_id: str
    symbol: str
    currency: str
    quantity: float
    total_cost: float
    average_unit_cost: float

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.account_id, self.symbol, self.currency)):
            raise ValueError("cost-basis identifiers are invalid")
        if not isinstance(self.quantity, float) or not math.isfinite(self.quantity) or self.quantity < 0:
            raise ValueError("cost-basis quantity is invalid")
        if not isinstance(self.total_cost, float) or not math.isfinite(self.total_cost) or self.total_cost < 0:
            raise ValueError("cost-basis total cost is invalid")
        if not isinstance(self.average_unit_cost, float) or not math.isfinite(self.average_unit_cost) or self.average_unit_cost < 0:
            raise ValueError("cost-basis average unit cost is invalid")
        if self.quantity == 0 and (self.total_cost != 0 or self.average_unit_cost != 0):
            raise ValueError("cost-basis closed position is inconsistent")
        if self.quantity > 0 and self.average_unit_cost != self.total_cost / self.quantity:
            raise ValueError("cost-basis average unit cost is inconsistent")


def calculate_cost_basis(transactions: Sequence[PortfolioTransaction]) -> tuple[CostBasis, ...]:
    if not isinstance(transactions, Sequence) or isinstance(transactions, (str, bytes)) or not transactions:
        raise ValueError("cost-basis calculation requires transactions")
    if not all(isinstance(transaction, PortfolioTransaction) for transaction in transactions):
        raise TypeError("cost-basis calculation requires portfolio transactions")
    if len({transaction.transaction_id for transaction in transactions}) != len(transactions):
        raise ValueError("cost-basis transaction IDs must be unique")
    states: dict[tuple[str, str, str], tuple[float, float]] = {}
    for transaction in sorted(transactions, key=lambda item: (item.recorded_at, item.transaction_id)):
        key = (transaction.account_id, transaction.symbol, transaction.currency)
        quantity, total_cost = states.get(key, (0.0, 0.0))
        if transaction.side is PortfolioTransactionSide.BUY:
            quantity += transaction.quantity
            total_cost += transaction.quantity * transaction.unit_price
        elif transaction.side is PortfolioTransactionSide.SELL:
            if transaction.quantity > quantity:
                raise ValueError("cost-basis transaction sells more than the long position")
            if transaction.quantity == quantity:
                quantity, total_cost = 0.0, 0.0
            else:
                quantity -= transaction.quantity
                total_cost = total_cost / (quantity + transaction.quantity) * quantity
        else:
            raise ValueError("cost-basis does not support short transactions")
        if not math.isfinite(quantity) or not math.isfinite(total_cost):
            raise ValueError("cost-basis calculation overflowed")
        states[key] = quantity, total_cost
    return tuple(
        CostBasis(account_id, symbol, currency, quantity, total_cost, 0.0 if quantity == 0 else total_cost / quantity)
        for (account_id, symbol, currency), (quantity, total_cost) in sorted(states.items())
    )
