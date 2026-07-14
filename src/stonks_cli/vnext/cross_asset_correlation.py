from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from stonks_cli.vnext.asset_returns import AssetReturnSeries


@dataclass(frozen=True)
class CrossAssetCorrelation:
    provider_id: str
    first_asset_id: str
    second_asset_id: str
    observations: int
    correlation: float

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.provider_id, self.first_asset_id, self.second_asset_id)):
            raise ValueError("cross-asset correlation identifiers are invalid")
        if self.first_asset_id >= self.second_asset_id:
            raise ValueError("cross-asset correlation asset order is invalid")
        if not isinstance(self.observations, int) or self.observations < 2:
            raise ValueError("cross-asset correlation requires at least two observations")
        if not isinstance(self.correlation, float) or not math.isfinite(self.correlation) or not -1 <= self.correlation <= 1:
            raise ValueError("cross-asset correlation value is invalid")


def calculate_cross_asset_correlations(series: Sequence[AssetReturnSeries]) -> tuple[CrossAssetCorrelation, ...]:
    if not isinstance(series, Sequence) or isinstance(series, (str, bytes)) or len(series) < 2:
        raise ValueError("cross-asset correlation requires at least two return series")
    if not all(isinstance(item, AssetReturnSeries) for item in series):
        raise TypeError("cross-asset correlation requires asset return series")
    if len({item.provider_id for item in series}) != 1 or len({item.provider_asset_id for item in series}) != len(series):
        raise ValueError("cross-asset correlation series are incompatible")
    ordered = tuple(sorted(series, key=lambda item: item.provider_asset_id))
    return tuple(_calculate_pair(first, second) for index, first in enumerate(ordered) for second in ordered[index + 1 :])


def _calculate_pair(first: AssetReturnSeries, second: AssetReturnSeries) -> CrossAssetCorrelation:
    first_days = tuple(item.day for item in first.returns)
    if first_days != tuple(item.day for item in second.returns):
        raise ValueError("cross-asset return dates are not aligned")
    first_values = tuple(item.return_fraction for item in first.returns)
    second_values = tuple(item.return_fraction for item in second.returns)
    first_mean = sum(first_values) / len(first_values)
    second_mean = sum(second_values) / len(second_values)
    covariance = sum((left - first_mean) * (right - second_mean) for left, right in zip(first_values, second_values, strict=True))
    first_variance = sum((value - first_mean) ** 2 for value in first_values)
    second_variance = sum((value - second_mean) ** 2 for value in second_values)
    if first_variance == 0 or second_variance == 0:
        raise ValueError("cross-asset correlation is undefined for zero-variance returns")
    return CrossAssetCorrelation(
        first.provider_id,
        first.provider_asset_id,
        second.provider_asset_id,
        len(first_values),
        covariance / math.sqrt(first_variance * second_variance),
    )
