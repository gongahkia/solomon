from __future__ import annotations

import math
from dataclasses import dataclass

from stonks_cli.vnext.asset_returns import AssetReturnSeries
from stonks_cli.vnext.realized_volatility import CRYPTO_TRADING_DAYS_PER_YEAR


@dataclass(frozen=True)
class RiskAdjustedPerformance:
    provider_id: str
    provider_asset_id: str
    daily_observations: int
    annualized_mean_return: float
    annualized_volatility: float
    sharpe_ratio: float

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id or not isinstance(self.provider_asset_id, str) or not self.provider_asset_id:
            raise ValueError("risk-adjusted identifiers are invalid")
        if not isinstance(self.daily_observations, int) or self.daily_observations < 2:
            raise ValueError("risk-adjusted performance requires at least two observations")
        if not all(isinstance(value, float) and math.isfinite(value) for value in (self.annualized_mean_return, self.annualized_volatility, self.sharpe_ratio)):
            raise ValueError("risk-adjusted performance values are invalid")
        if self.annualized_volatility < 0:
            raise ValueError("risk-adjusted volatility is invalid")


def calculate_risk_adjusted_performance(series: AssetReturnSeries) -> RiskAdjustedPerformance:
    if not isinstance(series, AssetReturnSeries):
        raise TypeError("asset return series is required")
    values = tuple(item.return_fraction for item in series.returns)
    if len(values) < 2:
        raise ValueError("risk-adjusted performance requires at least two returns")
    mean = sum(values) / len(values)
    annualized_mean = mean * CRYPTO_TRADING_DAYS_PER_YEAR
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    annualized_volatility = math.sqrt(variance * CRYPTO_TRADING_DAYS_PER_YEAR)
    if annualized_volatility == 0:
        if annualized_mean != 0:
            raise ValueError("risk-adjusted performance has undefined zero-volatility Sharpe ratio")
        sharpe_ratio = 0.0
    else:
        sharpe_ratio = annualized_mean / annualized_volatility
    return RiskAdjustedPerformance(
        series.provider_id, series.provider_asset_id, len(values), annualized_mean, annualized_volatility, sharpe_ratio
    )
