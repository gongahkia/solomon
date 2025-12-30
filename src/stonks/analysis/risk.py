from __future__ import annotations

import math


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def suggest_position_fraction_by_volatility(
    annualized_volatility: float,
    *,
    base_fraction: float = 0.10,
    reference_volatility: float = 0.20,
    min_fraction: float = 0.01,
    max_fraction: float = 0.20,
) -> float | None:
    """Suggest a portfolio fraction inversely proportional to volatility.

    Calibrated so that when annualized_volatility == reference_volatility,
    the suggested fraction is base_fraction.

    Returns None when volatility is non-finite or non-positive.
    """

    if not math.isfinite(annualized_volatility) or annualized_volatility <= 0:
        return None

    raw = base_fraction * (reference_volatility / annualized_volatility)
    return clamp(raw, min_fraction, max_fraction)


def scale_fractions_to_portfolio_cap(
    fractions: dict[str, float],
    *,
    max_portfolio_exposure_fraction: float,
) -> tuple[dict[str, float], float]:
    if max_portfolio_exposure_fraction <= 0:
        return {k: 0.0 for k in fractions}, 0.0

    total = sum(max(0.0, float(v)) for v in fractions.values())
    if total <= 0:
        return {k: 0.0 for k in fractions}, 0.0

    if total <= max_portfolio_exposure_fraction:
        return dict(fractions), 1.0

    factor = max_portfolio_exposure_fraction / total
    return {k: float(v) * factor for k, v in fractions.items()}, factor
