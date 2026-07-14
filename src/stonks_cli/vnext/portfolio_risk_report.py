from __future__ import annotations

import json

from stonks_cli.vnext.data_confidence import DataConfidenceScore
from stonks_cli.vnext.portfolio_exposure import PortfolioExposure
from stonks_cli.vnext.sgd_portfolio_nav import SGDPortfolioNAV
from stonks_cli.vnext.usd_portfolio_nav import USDPortfolioNAV


def render_portfolio_risk_report(
    exposure: PortfolioExposure, nav: SGDPortfolioNAV | USDPortfolioNAV, data_confidence: DataConfidenceScore
) -> str:
    if not isinstance(exposure, PortfolioExposure):
        raise TypeError("portfolio risk report requires exposure")
    if not isinstance(nav, (SGDPortfolioNAV, USDPortfolioNAV)):
        raise TypeError("portfolio risk report requires SGD or USD NAV")
    if not isinstance(data_confidence, DataConfidenceScore):
        raise TypeError("portfolio risk report requires data confidence")
    quote_currency = "SGD" if isinstance(nav, SGDPortfolioNAV) else "USD"
    if exposure.account_id != nav.account_id or exposure.quote_currency != quote_currency:
        raise ValueError("portfolio risk report exposure and NAV are incompatible")
    if nav.captured_at != data_confidence.evaluated_at:
        raise ValueError("portfolio risk report NAV and data confidence timestamps differ")
    net_asset_value = nav.net_asset_value_sgd if isinstance(nav, SGDPortfolioNAV) else nav.net_asset_value_usd
    if net_asset_value <= 0:
        raise ValueError("portfolio risk report NAV must be positive")
    return "\n".join(
        (
            "PORTFOLIO RISK REPORT",
            f"account_id: {json.dumps(exposure.account_id)}",
            f"captured_at: {nav.captured_at.isoformat().replace('+00:00', 'Z')}",
            f"currency: {quote_currency}",
            f"net_asset_value: {net_asset_value:.6f}",
            f"gross_exposure: {exposure.gross_exposure:.6f}",
            f"net_exposure: {exposure.net_exposure:.6f}",
            f"short_exposure: {exposure.short_exposure:.6f}",
            f"gross_leverage: {exposure.gross_exposure / net_asset_value:.6f}",
            f"net_leverage: {exposure.net_exposure / net_asset_value:.6f}",
            f"short_fraction: {exposure.short_exposure / net_asset_value:.6f}",
            f"data_confidence: {data_confidence.score:.6f}",
        )
    )
