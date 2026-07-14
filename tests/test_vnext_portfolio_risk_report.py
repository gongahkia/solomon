from datetime import UTC, datetime, timedelta

import pytest

from stonks_cli.vnext.data_confidence import DataConfidenceScore
from stonks_cli.vnext.portfolio_exposure import PortfolioExposure
from stonks_cli.vnext.portfolio_risk_report import render_portfolio_risk_report
from stonks_cli.vnext.usd_portfolio_nav import USDPortfolioNAV


def _confidence(evaluated_at: datetime) -> DataConfidenceScore:
    return DataConfidenceScore("fixture", evaluated_at, timedelta(minutes=10), 2, 1, ("https://example.test/stale",), 0.5)


def test_portfolio_risk_report_renders_deterministic_leverage_and_freshness_metrics():
    captured_at = datetime(2026, 7, 14, 12, tzinfo=UTC)
    exposure = PortfolioExposure("100", "USD", 750.0, 250.0, 1000.0, 500.0)
    nav = USDPortfolioNAV("100", captured_at, 1000.0, 0.0, 1000.0)

    rendered = render_portfolio_risk_report(exposure, nav, _confidence(captured_at))

    assert rendered == "\n".join(
        (
            "PORTFOLIO RISK REPORT",
            'account_id: "100"',
            "captured_at: 2026-07-14T12:00:00Z",
            "currency: USD",
            "net_asset_value: 1000.000000",
            "gross_exposure: 1000.000000",
            "net_exposure: 500.000000",
            "short_exposure: 250.000000",
            "gross_leverage: 1.000000",
            "net_leverage: 0.500000",
            "short_fraction: 0.250000",
            "data_confidence: 0.500000",
        )
    )


def test_portfolio_risk_report_fails_closed_for_incompatible_or_stale_inputs():
    captured_at = datetime(2026, 7, 14, 12, tzinfo=UTC)
    exposure = PortfolioExposure("100", "USD", 750.0, 250.0, 1000.0, 500.0)
    nav = USDPortfolioNAV("100", captured_at, 1000.0, 0.0, 1000.0)

    with pytest.raises(ValueError, match="timestamps differ"):
        render_portfolio_risk_report(exposure, nav, _confidence(captured_at + timedelta(seconds=1)))
    with pytest.raises(ValueError, match="incompatible"):
        render_portfolio_risk_report(PortfolioExposure("100", "SGD", 750.0, 250.0, 1000.0, 500.0), nav, _confidence(captured_at))
    with pytest.raises(TypeError, match="requires exposure"):
        render_portfolio_risk_report(None, nav, _confidence(captured_at))
