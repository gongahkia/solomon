from __future__ import annotations

import math
from dataclasses import dataclass

from stonks_cli.vnext.price_data import CanonicalPriceSeries


@dataclass(frozen=True)
class MeanReversionFactor:
    provider_id: str
    provider_asset_id: str
    window_days: int
    z_score: float

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id or not isinstance(self.provider_asset_id, str) or not self.provider_asset_id:
            raise ValueError("mean-reversion identifiers are invalid")
        if not isinstance(self.window_days, int) or isinstance(self.window_days, bool) or self.window_days < 2:
            raise ValueError("mean-reversion window must contain at least two days")
        if not isinstance(self.z_score, float) or not math.isfinite(self.z_score):
            raise ValueError("mean-reversion value is invalid")


def calculate_mean_reversion_factor(series: CanonicalPriceSeries, window_days: int) -> MeanReversionFactor:
    if not isinstance(series, CanonicalPriceSeries):
        raise TypeError("canonical price series is required")
    if not isinstance(window_days, int) or isinstance(window_days, bool) or not 2 <= window_days <= len(series.closes):
        raise ValueError("mean-reversion window is invalid")
    values = tuple(close.close_usd for close in series.closes[-window_days:])
    mean = sum(values) / window_days
    standard_deviation = math.sqrt(sum((value - mean) ** 2 for value in values) / window_days)
    z_score = 0.0 if standard_deviation == 0 else -(values[-1] - mean) / standard_deviation
    return MeanReversionFactor(series.provider_id, series.provider_asset_id, window_days, z_score)
