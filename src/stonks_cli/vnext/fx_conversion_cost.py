from __future__ import annotations

import math
from dataclasses import dataclass

from stonks_cli.vnext.fx_reference_rates import FXReferenceRate


@dataclass(frozen=True)
class FXConversionCostEstimate:
    base_currency: str
    quote_currency: str
    base_amount: float
    spread_bps: float
    gross_quote_amount: float
    estimated_cost_quote: float
    net_quote_amount: float

    def __post_init__(self) -> None:
        if not isinstance(self.base_currency, str) or not isinstance(self.quote_currency, str) or self.base_currency == self.quote_currency:
            raise ValueError("FX conversion cost currencies are invalid")
        if not isinstance(self.base_amount, float) or not math.isfinite(self.base_amount) or self.base_amount <= 0:
            raise ValueError("FX conversion cost base amount is invalid")
        if not isinstance(self.spread_bps, float) or not math.isfinite(self.spread_bps) or not 0 <= self.spread_bps <= 10_000:
            raise ValueError("FX conversion cost spread is invalid")
        if not all(isinstance(value, float) and math.isfinite(value) and value >= 0 for value in (self.gross_quote_amount, self.estimated_cost_quote, self.net_quote_amount)):
            raise ValueError("FX conversion cost quote amounts are invalid")
        if not math.isclose(self.net_quote_amount, self.gross_quote_amount - self.estimated_cost_quote, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("FX conversion cost net amount is inconsistent")


def estimate_fx_conversion_cost(base_amount: float, rate: FXReferenceRate, spread_bps: float) -> FXConversionCostEstimate:
    if not isinstance(rate, FXReferenceRate):
        raise TypeError("FX conversion cost requires a reference rate")
    if not isinstance(base_amount, float) or not math.isfinite(base_amount) or base_amount <= 0:
        raise ValueError("FX conversion cost base amount is invalid")
    if not isinstance(spread_bps, float) or not math.isfinite(spread_bps) or not 0 <= spread_bps <= 10_000:
        raise ValueError("FX conversion cost spread is invalid")
    gross_quote_amount = base_amount * rate.quote_amount_per_base
    estimated_cost_quote = gross_quote_amount * spread_bps / 10_000
    net_quote_amount = gross_quote_amount - estimated_cost_quote
    if not all(math.isfinite(value) and value >= 0 for value in (gross_quote_amount, estimated_cost_quote, net_quote_amount)):
        raise ValueError("FX conversion cost calculation overflowed")
    return FXConversionCostEstimate(
        rate.base_currency,
        rate.quote_currency,
        base_amount,
        spread_bps,
        gross_quote_amount,
        estimated_cost_quote,
        net_quote_amount,
    )
