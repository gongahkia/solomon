from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from stonks_cli.vnext.fx_reference_rates import FXReferenceRateBatch
from stonks_cli.vnext.portfolio_domain import PortfolioAssetClass, PortfolioSnapshot


@dataclass(frozen=True)
class AssetClassExposureLimit:
    asset_class: PortfolioAssetClass
    maximum_gross_exposure: float

    def __post_init__(self) -> None:
        if not isinstance(self.asset_class, PortfolioAssetClass):
            raise ValueError("asset-class exposure limit class is invalid")
        if not isinstance(self.maximum_gross_exposure, float) or not math.isfinite(self.maximum_gross_exposure) or self.maximum_gross_exposure < 0:
            raise ValueError("asset-class exposure limit is invalid")


def enforce_asset_class_exposure_limits(
    snapshot: PortfolioSnapshot, fx_rates: FXReferenceRateBatch, limits: Sequence[AssetClassExposureLimit]
) -> None:
    if not isinstance(snapshot, PortfolioSnapshot) or not isinstance(fx_rates, FXReferenceRateBatch):
        raise TypeError("asset-class exposure limits require a portfolio snapshot and FX rates")
    if not isinstance(limits, Sequence) or isinstance(limits, (str, bytes)) or not all(isinstance(limit, AssetClassExposureLimit) for limit in limits):
        raise ValueError("asset-class exposure limits are invalid")
    if len({limit.asset_class for limit in limits}) != len(limits):
        raise ValueError("asset-class exposure limits must be unique")
    rate_by_currency = {rate.base_currency: rate.quote_amount_per_base for rate in fx_rates.rates}
    exposures: dict[PortfolioAssetClass, list[float]] = {}
    for holding in snapshot.holdings:
        rate = 1.0 if holding.currency == fx_rates.quote_currency else rate_by_currency.get(holding.currency)
        if rate is None:
            raise ValueError(f"asset-class exposure is missing FX reference rate:{holding.currency}")
        exposures.setdefault(holding.asset_class, []).append(abs(holding.market_value * rate))
    limits_by_class = {limit.asset_class: limit.maximum_gross_exposure for limit in limits}
    if set(exposures) - set(limits_by_class):
        raise ValueError("asset-class exposure limit is missing")
    for asset_class, values in exposures.items():
        exposure = math.fsum(values)
        if not math.isfinite(exposure):
            raise ValueError("asset-class exposure calculation overflowed")
        if exposure > limits_by_class[asset_class]:
            raise ValueError(f"asset-class exposure limit exceeded:{asset_class}")
