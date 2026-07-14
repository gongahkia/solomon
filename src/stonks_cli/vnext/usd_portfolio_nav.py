from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from stonks_cli.vnext.cash_ledger import CashLedger
from stonks_cli.vnext.foundation import as_utc
from stonks_cli.vnext.fx_reference_rates import FXReferenceRateBatch
from stonks_cli.vnext.portfolio_domain import PortfolioSnapshot


@dataclass(frozen=True)
class USDPortfolioNAV:
    account_id: str
    captured_at: datetime
    holdings_value_usd: float
    cash_value_usd: float
    net_asset_value_usd: float

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, str) or not self.account_id:
            raise ValueError("USD NAV account ID is invalid")
        object.__setattr__(self, "captured_at", as_utc(self.captured_at))
        if not all(isinstance(value, float) and math.isfinite(value) for value in (self.holdings_value_usd, self.cash_value_usd, self.net_asset_value_usd)):
            raise ValueError("USD NAV values are invalid")
        if not math.isclose(self.net_asset_value_usd, self.holdings_value_usd + self.cash_value_usd, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("USD NAV total is inconsistent")


def calculate_usd_portfolio_nav(
    snapshot: PortfolioSnapshot, cash_ledger: CashLedger, fx_rates: FXReferenceRateBatch
) -> USDPortfolioNAV:
    if not isinstance(snapshot, PortfolioSnapshot):
        raise TypeError("USD NAV requires a portfolio snapshot")
    if not isinstance(cash_ledger, CashLedger):
        raise TypeError("USD NAV requires a cash ledger")
    if not isinstance(fx_rates, FXReferenceRateBatch):
        raise TypeError("USD NAV requires FX reference rates")
    if snapshot.provider_id != cash_ledger.provider_id or snapshot.account_id != cash_ledger.account_id:
        raise ValueError("USD NAV holdings and cash ledger are incompatible")
    if snapshot.captured_at != cash_ledger.captured_at:
        raise ValueError("USD NAV holdings and cash ledger timestamps differ")
    if fx_rates.quote_currency != "USD":
        raise ValueError("USD NAV requires USD FX reference rates")
    rate_by_currency = {rate.base_currency: rate.quote_amount_per_base for rate in fx_rates.rates}
    holding_values = tuple(_convert_to_usd(holding.market_value, holding.currency, rate_by_currency) for holding in snapshot.holdings)
    cash_values = tuple(_convert_to_usd(balance.amount, balance.currency, rate_by_currency) for balance in cash_ledger.balances)
    try:
        holdings_value = math.fsum(holding_values)
        cash_value = math.fsum(cash_values)
        total_value = math.fsum((holdings_value, cash_value))
    except OverflowError as error:
        raise ValueError("USD NAV calculation overflowed") from error
    return USDPortfolioNAV(snapshot.account_id, snapshot.captured_at, holdings_value, cash_value, total_value)


def _convert_to_usd(amount: float, currency: str, rate_by_currency: dict[str, float]) -> float:
    if currency == "USD":
        return amount
    rate = rate_by_currency.get(currency)
    if rate is None:
        raise ValueError(f"USD NAV is missing FX reference rate:{currency}")
    converted = amount * rate
    if not math.isfinite(converted):
        raise ValueError("USD NAV conversion overflowed")
    return converted
