from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.fx_reference_rates import FXReferenceRate, FXReferenceRateBatch
from stonks_cli.vnext.portfolio_domain import PortfolioAssetClass, PortfolioHolding, PortfolioSnapshot
from stonks_cli.vnext.rebalance_drift import RebalanceTarget, calculate_rebalance_drift


def test_rebalance_drift_calculates_canonical_current_minus_target_weights():
    timestamp = datetime(2026, 7, 14, 12, tzinfo=UTC)
    snapshot = PortfolioSnapshot("moomoo", "100", timestamp, (PortfolioHolding("100", "sg", "SG.D05", PortfolioAssetClass.EQUITY, 1.0, "SGD", 100.0), PortfolioHolding("100", "us", "US.AAPL", PortfolioAssetClass.EQUITY, 1.0, "USD", 300.0)))
    rates = FXReferenceRateBatch("fixture", "USD", (FXReferenceRate("SGD", "USD", 0.75, timestamp),))
    drift = calculate_rebalance_drift(snapshot, rates, (RebalanceTarget("US.AAPL", 0.75), RebalanceTarget("SG.D05", 0.25)))
    assert [(item.symbol, item.drift_fraction) for item in drift] == [("SG.D05", pytest.approx(-0.05)), ("US.AAPL", pytest.approx(0.05))]


def test_rebalance_drift_fails_closed_for_mismatched_or_non_normalized_targets():
    timestamp = datetime(2026, 7, 14, 12, tzinfo=UTC)
    snapshot = PortfolioSnapshot("moomoo", "100", timestamp, (PortfolioHolding("100", "us", "US.AAPL", PortfolioAssetClass.EQUITY, 1.0, "USD", 100.0),))
    rates = FXReferenceRateBatch("fixture", "USD", (FXReferenceRate("SGD", "USD", 0.75, timestamp),))
    with pytest.raises(ValueError, match="normalized"):
        calculate_rebalance_drift(snapshot, rates, (RebalanceTarget("US.AAPL", 0.5),))
    with pytest.raises(ValueError, match="do not match"):
        calculate_rebalance_drift(snapshot, rates, (RebalanceTarget("SG.D05", 1.0),))
