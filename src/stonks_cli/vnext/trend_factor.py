from __future__ import annotations

import math
from dataclasses import dataclass

from stonks_cli.vnext.price_data import CanonicalPriceSeries
from stonks_cli.vnext.realized_volatility import CRYPTO_TRADING_DAYS_PER_YEAR


@dataclass(frozen=True)
class TrendFactor:
    provider_id: str
    provider_asset_id: str
    window_days: int
    annualized_log_slope: float

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id or not isinstance(self.provider_asset_id, str) or not self.provider_asset_id:
            raise ValueError("trend-factor identifiers are invalid")
        if not isinstance(self.window_days, int) or isinstance(self.window_days, bool) or self.window_days < 2:
            raise ValueError("trend-factor window must contain at least two days")
        if not isinstance(self.annualized_log_slope, float) or not math.isfinite(self.annualized_log_slope):
            raise ValueError("trend-factor value is invalid")


def calculate_trend_factor(series: CanonicalPriceSeries, window_days: int) -> TrendFactor:
    if not isinstance(series, CanonicalPriceSeries):
        raise TypeError("canonical price series is required")
    if not isinstance(window_days, int) or isinstance(window_days, bool) or not 2 <= window_days <= len(series.closes):
        raise ValueError("trend-factor window is invalid")
    closes = series.closes[-window_days:]
    x_mean = (window_days - 1) / 2
    log_prices = tuple(math.log(close.close_usd) for close in closes)
    y_mean = sum(log_prices) / window_days
    denominator = sum((index - x_mean) ** 2 for index in range(window_days))
    slope = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(log_prices)) / denominator
    return TrendFactor(series.provider_id, series.provider_asset_id, window_days, slope * CRYPTO_TRADING_DAYS_PER_YEAR)
