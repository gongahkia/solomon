from __future__ import annotations

import math

from stonks_cli.vnext.fx_reference_rates import FXReferenceRateBatch
from stonks_cli.vnext.portfolio_domain import PortfolioAssetClass, PortfolioSnapshot


def enforce_crypto_allocation_limit(
    snapshot: PortfolioSnapshot, fx_rates: FXReferenceRateBatch, maximum_allocation_fraction: float
) -> None:
    if not isinstance(snapshot, PortfolioSnapshot) or not isinstance(fx_rates, FXReferenceRateBatch):
        raise TypeError("crypto allocation limit requires a portfolio snapshot and FX rates")
    if (
        not isinstance(maximum_allocation_fraction, float)
        or not math.isfinite(maximum_allocation_fraction)
        or not 0 <= maximum_allocation_fraction <= 1
    ):
        raise ValueError("crypto allocation limit is invalid")
    rates = {rate.base_currency: rate.quote_amount_per_base for rate in fx_rates.rates}
    values: list[tuple[PortfolioAssetClass, float]] = []
    for holding in snapshot.holdings:
        rate = 1.0 if holding.currency == fx_rates.quote_currency else rates.get(holding.currency)
        if rate is None:
            raise ValueError(f"crypto allocation is missing FX reference rate:{holding.currency}")
        value = abs(holding.market_value * rate)
        if not math.isfinite(value):
            raise ValueError("crypto allocation conversion overflowed")
        values.append((holding.asset_class, value))
    try:
        total = math.fsum(value for _, value in values)
        crypto = math.fsum(value for asset_class, value in values if asset_class is PortfolioAssetClass.CRYPTO)
    except OverflowError as error:
        raise ValueError("crypto allocation calculation overflowed") from error
    if not math.isfinite(total) or total <= 0:
        raise ValueError("crypto allocation portfolio value is invalid")
    if crypto / total > maximum_allocation_fraction:
        raise ValueError("crypto allocation limit exceeded")
