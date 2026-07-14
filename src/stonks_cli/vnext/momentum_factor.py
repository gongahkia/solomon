from __future__ import annotations

import math
from dataclasses import dataclass

from stonks_cli.vnext.price_data import CanonicalPriceSeries


@dataclass(frozen=True)
class MomentumFactor:
    provider_id: str
    provider_asset_id: str
    window_days: int
    return_fraction: float

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id or not isinstance(self.provider_asset_id, str) or not self.provider_asset_id:
            raise ValueError("momentum-factor identifiers are invalid")
        if not isinstance(self.window_days, int) or isinstance(self.window_days, bool) or self.window_days < 2:
            raise ValueError("momentum-factor window must contain at least two days")
        if not isinstance(self.return_fraction, float) or not math.isfinite(self.return_fraction):
            raise ValueError("momentum-factor value is invalid")


def calculate_momentum_factor(series: CanonicalPriceSeries, window_days: int) -> MomentumFactor:
    if not isinstance(series, CanonicalPriceSeries):
        raise TypeError("canonical price series is required")
    if not isinstance(window_days, int) or isinstance(window_days, bool) or not 2 <= window_days <= len(series.closes):
        raise ValueError("momentum-factor window is invalid")
    closes = series.closes[-window_days:]
    return MomentumFactor(series.provider_id, series.provider_asset_id, window_days, closes[-1].close_usd / closes[0].close_usd - 1.0)
