from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.fx_reference_rates import FXReferenceRate, FXReferenceRateBatch
from stonks_cli.vnext.portfolio_domain import PortfolioAssetClass, PortfolioHolding, PortfolioSnapshot
from stonks_cli.vnext.sector_limits import SectorConcentrationLimit, enforce_sector_concentration_limits


def test_sector_limits_enforce_converted_gross_caps():
    timestamp = datetime(2026, 7, 14, 12, tzinfo=UTC)
    snapshot = PortfolioSnapshot("moomoo", "100", timestamp, (PortfolioHolding("100", "aapl", "US.AAPL", PortfolioAssetClass.EQUITY, -1.0, "USD", -100.0),))
    rates = FXReferenceRateBatch("fixture", "SGD", (FXReferenceRate("USD", "SGD", 1.34, timestamp),))

    assert enforce_sector_concentration_limits(snapshot, rates, {"US.AAPL": "technology"}, (SectorConcentrationLimit("technology", 134.0),)) is None


def test_sector_limits_fail_closed_for_missing_classification_or_breach():
    timestamp = datetime(2026, 7, 14, 12, tzinfo=UTC)
    snapshot = PortfolioSnapshot("moomoo", "100", timestamp, (PortfolioHolding("100", "aapl", "US.AAPL", PortfolioAssetClass.EQUITY, 1.0, "USD", 100.0),))
    rates = FXReferenceRateBatch("fixture", "SGD", (FXReferenceRate("USD", "SGD", 1.34, timestamp),))

    with pytest.raises(ValueError, match="classification is missing"):
        enforce_sector_concentration_limits(snapshot, rates, {}, ())
    with pytest.raises(ValueError, match="exceeded"):
        enforce_sector_concentration_limits(snapshot, rates, {"US.AAPL": "technology"}, (SectorConcentrationLimit("technology", 133.0),))
