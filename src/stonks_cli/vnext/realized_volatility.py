from __future__ import annotations

import math
from dataclasses import dataclass

from stonks_cli.vnext.asset_returns import AssetReturnSeries

CRYPTO_TRADING_DAYS_PER_YEAR = 365


@dataclass(frozen=True)
class RealizedVolatility:
    provider_id: str
    provider_asset_id: str
    daily_observations: int
    annualized_volatility: float

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not isinstance(self.provider_asset_id, str):
            raise ValueError("realized-volatility identifiers are invalid")
        if not isinstance(self.daily_observations, int) or self.daily_observations < 2:
            raise ValueError("realized-volatility requires at least two daily observations")
        if not isinstance(self.annualized_volatility, float) or not math.isfinite(self.annualized_volatility) or self.annualized_volatility < 0:
            raise ValueError("realized volatility is invalid")


def calculate_realized_volatility(series: AssetReturnSeries) -> RealizedVolatility:
    if not isinstance(series, AssetReturnSeries):
        raise TypeError("asset return series is required")
    values = tuple(item.return_fraction for item in series.returns)
    if len(values) < 2:
        raise ValueError("realized volatility requires at least two returns")
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return RealizedVolatility(series.provider_id, series.provider_asset_id, len(values), math.sqrt(variance * CRYPTO_TRADING_DAYS_PER_YEAR))
