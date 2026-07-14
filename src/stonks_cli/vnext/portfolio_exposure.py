from __future__ import annotations

import math
import re
from dataclasses import dataclass

from stonks_cli.vnext.fx_reference_rates import FXReferenceRateBatch
from stonks_cli.vnext.portfolio_domain import PortfolioSnapshot

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")


@dataclass(frozen=True)
class PortfolioExposure:
    account_id: str
    quote_currency: str
    long_exposure: float
    short_exposure: float
    gross_exposure: float
    net_exposure: float

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, str) or not self.account_id:
            raise ValueError("portfolio exposure account ID is invalid")
        if not isinstance(self.quote_currency, str) or not _CURRENCY_PATTERN.fullmatch(self.quote_currency):
            raise ValueError("portfolio exposure quote currency is invalid")
        if not all(isinstance(value, float) and math.isfinite(value) for value in (self.long_exposure, self.short_exposure, self.gross_exposure, self.net_exposure)):
            raise ValueError("portfolio exposure values are invalid")
        if self.long_exposure < 0 or self.short_exposure < 0 or self.gross_exposure < 0:
            raise ValueError("portfolio exposure magnitudes are invalid")
        if not math.isclose(self.gross_exposure, self.long_exposure + self.short_exposure, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("portfolio gross exposure is inconsistent")
        if not math.isclose(self.net_exposure, self.long_exposure - self.short_exposure, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("portfolio net exposure is inconsistent")


def calculate_portfolio_exposure(snapshot: PortfolioSnapshot, fx_rates: FXReferenceRateBatch) -> PortfolioExposure:
    if not isinstance(snapshot, PortfolioSnapshot):
        raise TypeError("portfolio exposure requires a portfolio snapshot")
    if not isinstance(fx_rates, FXReferenceRateBatch):
        raise TypeError("portfolio exposure requires FX reference rates")
    rate_by_currency = {rate.base_currency: rate.quote_amount_per_base for rate in fx_rates.rates}
    values = tuple(_convert_value(holding.market_value, holding.currency, fx_rates.quote_currency, rate_by_currency) for holding in snapshot.holdings)
    try:
        long_exposure = math.fsum(value for value in values if value > 0)
        short_exposure = math.fsum(-value for value in values if value < 0)
        gross_exposure = math.fsum((long_exposure, short_exposure))
        net_exposure = math.fsum((long_exposure, -short_exposure))
    except OverflowError as error:
        raise ValueError("portfolio exposure calculation overflowed") from error
    return PortfolioExposure(snapshot.account_id, fx_rates.quote_currency, long_exposure, short_exposure, gross_exposure, net_exposure)


def _convert_value(amount: float, currency: str, quote_currency: str, rate_by_currency: dict[str, float]) -> float:
    if currency == quote_currency:
        return amount
    rate = rate_by_currency.get(currency)
    if rate is None:
        raise ValueError(f"portfolio exposure is missing FX reference rate:{currency}")
    converted = amount * rate
    if not math.isfinite(converted):
        raise ValueError("portfolio exposure conversion overflowed")
    return converted
