from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from stonks_cli.vnext.fx_reference_rates import FXReferenceRateBatch
from stonks_cli.vnext.portfolio_domain import PortfolioSnapshot


@dataclass(frozen=True)
class SectorConcentrationLimit:
    sector: str
    maximum_gross_exposure: float

    def __post_init__(self) -> None:
        if not isinstance(self.sector, str) or not self.sector:
            raise ValueError("sector concentration limit sector is invalid")
        if not isinstance(self.maximum_gross_exposure, float) or not math.isfinite(self.maximum_gross_exposure) or self.maximum_gross_exposure < 0:
            raise ValueError("sector concentration limit is invalid")


def enforce_sector_concentration_limits(
    snapshot: PortfolioSnapshot, fx_rates: FXReferenceRateBatch, classifications: Mapping[str, str], limits: tuple[SectorConcentrationLimit, ...]
) -> None:
    if not isinstance(snapshot, PortfolioSnapshot) or not isinstance(fx_rates, FXReferenceRateBatch):
        raise TypeError("sector limits require a portfolio snapshot and FX rates")
    if not isinstance(classifications, Mapping) or not all(isinstance(symbol, str) and symbol and isinstance(sector, str) and sector for symbol, sector in classifications.items()):
        raise ValueError("sector classifications are invalid")
    if not isinstance(limits, tuple) or not all(isinstance(limit, SectorConcentrationLimit) for limit in limits):
        raise ValueError("sector concentration limits are invalid")
    caps = {limit.sector: limit.maximum_gross_exposure for limit in limits}
    if len(caps) != len(limits):
        raise ValueError("sector concentration limits must be unique")
    rates = {rate.base_currency: rate.quote_amount_per_base for rate in fx_rates.rates}
    exposures: dict[str, list[float]] = {}
    for holding in snapshot.holdings:
        sector = classifications.get(holding.symbol)
        if sector is None:
            raise ValueError(f"sector classification is missing:{holding.symbol}")
        rate = 1.0 if holding.currency == fx_rates.quote_currency else rates.get(holding.currency)
        if rate is None:
            raise ValueError(f"sector concentration is missing FX reference rate:{holding.currency}")
        exposures.setdefault(sector, []).append(abs(holding.market_value * rate))
    if set(exposures) - set(caps):
        raise ValueError("sector concentration limit is missing")
    for sector, values in exposures.items():
        exposure = math.fsum(values)
        if not math.isfinite(exposure):
            raise ValueError("sector concentration calculation overflowed")
        if exposure > caps[sector]:
            raise ValueError(f"sector concentration limit exceeded:{sector}")
