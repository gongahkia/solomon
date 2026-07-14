from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from stonks_cli.vnext.fx_reference_rates import FXReferenceRateBatch
from stonks_cli.vnext.portfolio_domain import PortfolioSnapshot


@dataclass(frozen=True)
class RebalanceTarget:
    symbol: str
    target_weight: float

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise ValueError("rebalance target symbol is invalid")
        if not isinstance(self.target_weight, float) or not math.isfinite(self.target_weight) or not 0 <= self.target_weight <= 1:
            raise ValueError("rebalance target weight is invalid")


@dataclass(frozen=True)
class RebalanceDrift:
    symbol: str
    current_weight: float
    target_weight: float
    drift_fraction: float

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise ValueError("rebalance drift symbol is invalid")
        if not all(isinstance(value, float) and math.isfinite(value) for value in (self.current_weight, self.target_weight, self.drift_fraction)):
            raise ValueError("rebalance drift values are invalid")
        if not 0 <= self.current_weight <= 1 or not 0 <= self.target_weight <= 1:
            raise ValueError("rebalance drift weights are invalid")
        if not math.isclose(self.drift_fraction, self.current_weight - self.target_weight, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("rebalance drift is inconsistent")


def calculate_rebalance_drift(
    snapshot: PortfolioSnapshot, fx_rates: FXReferenceRateBatch, targets: Sequence[RebalanceTarget]
) -> tuple[RebalanceDrift, ...]:
    if not isinstance(snapshot, PortfolioSnapshot) or not isinstance(fx_rates, FXReferenceRateBatch):
        raise TypeError("rebalance drift requires a portfolio snapshot and FX rates")
    if not isinstance(targets, Sequence) or isinstance(targets, (str, bytes)) or not targets or not all(isinstance(target, RebalanceTarget) for target in targets):
        raise ValueError("rebalance targets are invalid")
    if len({target.symbol for target in targets}) != len(targets) or not math.isclose(sum(target.target_weight for target in targets), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("rebalance targets must be unique and normalized")
    rates = {rate.base_currency: rate.quote_amount_per_base for rate in fx_rates.rates}
    values: dict[str, float] = {}
    for holding in snapshot.holdings:
        if holding.market_value <= 0:
            raise ValueError("rebalance drift requires long-only holdings")
        rate = 1.0 if holding.currency == fx_rates.quote_currency else rates.get(holding.currency)
        if rate is None:
            raise ValueError(f"rebalance drift is missing FX reference rate:{holding.currency}")
        values[holding.symbol] = holding.market_value * rate
    if set(values) != {target.symbol for target in targets}:
        raise ValueError("rebalance targets do not match holdings")
    total = math.fsum(values.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("rebalance holding value is invalid")
    return tuple(
        RebalanceDrift(target.symbol, values[target.symbol] / total, target.target_weight, values[target.symbol] / total - target.target_weight)
        for target in sorted(targets, key=lambda item: item.symbol)
    )
