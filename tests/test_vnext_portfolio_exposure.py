from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.fx_reference_rates import FXReferenceRate, FXReferenceRateBatch
from stonks_cli.vnext.portfolio_domain import PortfolioAssetClass, PortfolioHolding, PortfolioSnapshot
from stonks_cli.vnext.portfolio_exposure import calculate_portfolio_exposure


def test_portfolio_exposure_calculates_long_short_gross_and_net_in_quote_currency():
    captured_at = datetime(2026, 7, 14, 12, tzinfo=UTC)
    snapshot = PortfolioSnapshot(
        "moomoo",
        "100",
        captured_at,
        (
            PortfolioHolding("100", "sg-short", "SG.D05", PortfolioAssetClass.EQUITY, -1.0, "SGD", -100.0),
            PortfolioHolding("100", "us-long", "US.AAPL", PortfolioAssetClass.EQUITY, 2.0, "USD", 400.0),
        ),
    )
    rates = FXReferenceRateBatch("fixture", "USD", (FXReferenceRate("SGD", "USD", 0.75, captured_at),))

    exposure = calculate_portfolio_exposure(snapshot, rates)

    assert exposure.long_exposure == 400.0
    assert exposure.short_exposure == 75.0
    assert exposure.gross_exposure == 475.0
    assert exposure.net_exposure == 325.0


def test_portfolio_exposure_fails_closed_for_missing_rate_or_invalid_inputs():
    captured_at = datetime(2026, 7, 14, 12, tzinfo=UTC)
    snapshot = PortfolioSnapshot(
        "moomoo", "100", captured_at, (PortfolioHolding("100", "sg", "SG.D05", PortfolioAssetClass.EQUITY, 1.0, "SGD", 100.0),)
    )
    rates = FXReferenceRateBatch("fixture", "USD", (FXReferenceRate("EUR", "USD", 1.1, captured_at),))

    with pytest.raises(ValueError, match="missing FX"):
        calculate_portfolio_exposure(snapshot, rates)
    with pytest.raises(TypeError, match="requires a portfolio snapshot"):
        calculate_portfolio_exposure(None, rates)
