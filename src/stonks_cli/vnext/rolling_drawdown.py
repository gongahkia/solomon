from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from stonks_cli.vnext.daily_closing_prices import DailyClosingPriceIngestion
from stonks_cli.vnext.price_data import CanonicalPriceSeries


@dataclass(frozen=True)
class DailyDrawdown:
    day: date
    drawdown_fraction: float

    def __post_init__(self) -> None:
        if not isinstance(self.day, date):
            raise TypeError("drawdown date is invalid")
        if not isinstance(self.drawdown_fraction, float) or not math.isfinite(self.drawdown_fraction) or self.drawdown_fraction > 0:
            raise ValueError("drawdown value is invalid")


@dataclass(frozen=True)
class RollingDrawdownSeries:
    provider_id: str
    provider_asset_id: str
    drawdowns: tuple[DailyDrawdown, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id or not isinstance(self.provider_asset_id, str) or not self.provider_asset_id:
            raise ValueError("drawdown identifiers are invalid")
        if not isinstance(self.drawdowns, tuple) or not self.drawdowns or not all(isinstance(item, DailyDrawdown) for item in self.drawdowns):
            raise ValueError("drawdown series is invalid")
        days = tuple(item.day for item in self.drawdowns)
        if days != tuple(sorted(days)) or len(set(days)) != len(days):
            raise ValueError("drawdown series must be chronological and unique")


def calculate_rolling_drawdown(ingestion: DailyClosingPriceIngestion) -> tuple[RollingDrawdownSeries, ...]:
    if not isinstance(ingestion, DailyClosingPriceIngestion):
        raise TypeError("daily closing-price ingestion is required")
    return tuple(_calculate_series_drawdown(series) for series in ingestion.series)


def _calculate_series_drawdown(series: CanonicalPriceSeries) -> RollingDrawdownSeries:
    peak = 0.0
    drawdowns: list[DailyDrawdown] = []
    for close in series.closes:
        peak = max(peak, close.close_usd)
        drawdowns.append(DailyDrawdown(close.day, close.close_usd / peak - 1.0))
    return RollingDrawdownSeries(series.provider_id, series.provider_asset_id, tuple(drawdowns))
