from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.liquidity_constraints import enforce_minimum_liquidity_constraints
from stonks_cli.vnext.portfolio_domain import PortfolioAssetClass, PortfolioHolding, PortfolioSnapshot


def test_minimum_liquidity_constraints_require_observations_above_floor():
    snapshot = PortfolioSnapshot("moomoo", "100", datetime(2026, 7, 14, tzinfo=UTC), (PortfolioHolding("100", "aapl", "US.AAPL", PortfolioAssetClass.EQUITY, 1.0, "USD", 100.0),))
    assert enforce_minimum_liquidity_constraints(snapshot, {"US.AAPL": 1_000_000.0}, 500_000.0) is None


def test_minimum_liquidity_constraints_fail_closed_for_missing_or_insufficient_observations():
    snapshot = PortfolioSnapshot("moomoo", "100", datetime(2026, 7, 14, tzinfo=UTC), (PortfolioHolding("100", "aapl", "US.AAPL", PortfolioAssetClass.EQUITY, 1.0, "USD", 100.0),))
    with pytest.raises(ValueError, match="missing"):
        enforce_minimum_liquidity_constraints(snapshot, {}, 1.0)
    with pytest.raises(ValueError, match="not met"):
        enforce_minimum_liquidity_constraints(snapshot, {"US.AAPL": 100.0}, 101.0)
