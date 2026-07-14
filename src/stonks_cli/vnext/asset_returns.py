from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from stonks_cli.vnext.daily_closing_prices import DailyClosingPriceIngestion
from stonks_cli.vnext.price_data import CanonicalPriceSeries


@dataclass(frozen=True)
class DailyAssetReturn:
    day: date
    return_fraction: float

    def __post_init__(self) -> None:
        if not isinstance(self.day, date):
            raise TypeError("asset return date is invalid")
        if not isinstance(self.return_fraction, float) or not math.isfinite(self.return_fraction):
            raise ValueError("asset return is invalid")


@dataclass(frozen=True)
class AssetReturnSeries:
    provider_id: str
    provider_asset_id: str
    returns: tuple[DailyAssetReturn, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise ValueError("asset-return provider ID is invalid")
        if not isinstance(self.provider_asset_id, str) or not self.provider_asset_id:
            raise ValueError("asset-return provider asset ID is invalid")
        if not isinstance(self.returns, tuple) or not self.returns or not all(isinstance(item, DailyAssetReturn) for item in self.returns):
            raise ValueError("asset returns are invalid")
        days = tuple(item.day for item in self.returns)
        if days != tuple(sorted(days)) or len(set(days)) != len(days):
            raise ValueError("asset returns must be chronological and unique")


def calculate_asset_returns(ingestion: DailyClosingPriceIngestion) -> tuple[AssetReturnSeries, ...]:
    if not isinstance(ingestion, DailyClosingPriceIngestion):
        raise TypeError("daily closing-price ingestion is required")
    return tuple(_calculate_series_returns(series) for series in ingestion.series)


def _calculate_series_returns(series: CanonicalPriceSeries) -> AssetReturnSeries:
    if len(series.closes) < 2:
        raise ValueError("asset-return series requires at least two daily closes")
    returns = tuple(
        DailyAssetReturn(current.day, current.close_usd / previous.close_usd - 1.0)
        for previous, current in zip(series.closes, series.closes[1:], strict=False)
    )
    return AssetReturnSeries(series.provider_id, series.provider_asset_id, returns)
