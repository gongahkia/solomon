from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from stonks_cli.vnext.fx_reference_rates import FXReferenceRateBatch
from stonks_cli.vnext.portfolio_domain import PortfolioSnapshot


@dataclass(frozen=True)
class SingleAssetExposureLimit:
    symbol: str
    maximum_gross_exposure: float

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise ValueError("single-asset limit symbol is invalid")
        if not isinstance(self.maximum_gross_exposure, float) or not math.isfinite(self.maximum_gross_exposure) or self.maximum_gross_exposure < 0:
            raise ValueError("single-asset limit is invalid")


def enforce_single_asset_limits(
    snapshot: PortfolioSnapshot, fx_rates: FXReferenceRateBatch, limits: Sequence[SingleAssetExposureLimit]
) -> None:
    if not isinstance(snapshot, PortfolioSnapshot) or not isinstance(fx_rates, FXReferenceRateBatch):
        raise TypeError("single-asset limits require a portfolio snapshot and FX rates")
    if not isinstance(limits, Sequence) or isinstance(limits, (str, bytes)) or not all(isinstance(limit, SingleAssetExposureLimit) for limit in limits):
        raise ValueError("single-asset limits are invalid")
    if len({limit.symbol for limit in limits}) != len(limits):
        raise ValueError("single-asset limits must be unique")
    rates = {rate.base_currency: rate.quote_amount_per_base for rate in fx_rates.rates}
    exposures: dict[str, list[float]] = {}
    for holding in snapshot.holdings:
        rate = 1.0 if holding.currency == fx_rates.quote_currency else rates.get(holding.currency)
        if rate is None:
            raise ValueError(f"single-asset limit is missing FX reference rate:{holding.currency}")
        exposures.setdefault(holding.symbol, []).append(abs(holding.market_value * rate))
    caps = {limit.symbol: limit.maximum_gross_exposure for limit in limits}
    if set(exposures) - set(caps):
        raise ValueError("single-asset limit is missing")
    for symbol, values in exposures.items():
        exposure = math.fsum(values)
        if not math.isfinite(exposure):
            raise ValueError("single-asset exposure calculation overflowed")
        if exposure > caps[symbol]:
            raise ValueError(f"single-asset limit exceeded:{symbol}")
