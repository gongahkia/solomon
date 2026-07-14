from __future__ import annotations

import math
from collections.abc import Mapping

from stonks_cli.vnext.portfolio_domain import PortfolioSnapshot


def enforce_minimum_liquidity_constraints(
    snapshot: PortfolioSnapshot, liquidity_usd_by_symbol: Mapping[str, float], minimum_liquidity_usd: float
) -> None:
    if not isinstance(snapshot, PortfolioSnapshot):
        raise TypeError("liquidity constraints require a portfolio snapshot")
    if not isinstance(liquidity_usd_by_symbol, Mapping) or not all(
        isinstance(symbol, str) and symbol and isinstance(value, float) and math.isfinite(value) and value >= 0
        for symbol, value in liquidity_usd_by_symbol.items()
    ):
        raise ValueError("liquidity observations are invalid")
    if not isinstance(minimum_liquidity_usd, float) or not math.isfinite(minimum_liquidity_usd) or minimum_liquidity_usd < 0:
        raise ValueError("minimum liquidity is invalid")
    for holding in snapshot.holdings:
        liquidity = liquidity_usd_by_symbol.get(holding.symbol)
        if liquidity is None:
            raise ValueError(f"liquidity observation is missing:{holding.symbol}")
        if liquidity < minimum_liquidity_usd:
            raise ValueError(f"minimum liquidity is not met:{holding.symbol}")
