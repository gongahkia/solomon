from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.asset_class_limits import AssetClassExposureLimit, enforce_asset_class_exposure_limits
from stonks_cli.vnext.fx_reference_rates import FXReferenceRate, FXReferenceRateBatch
from stonks_cli.vnext.portfolio_domain import PortfolioAssetClass, PortfolioHolding, PortfolioSnapshot


def test_asset_class_exposure_limits_enforce_converted_gross_caps():
    captured_at = datetime(2026, 7, 14, 12, tzinfo=UTC)
    snapshot = PortfolioSnapshot(
        "moomoo",
        "100",
        captured_at,
        (
            PortfolioHolding("100", "btc", "BTC", PortfolioAssetClass.CRYPTO, 1.0, "USD", 200.0),
            PortfolioHolding("100", "short", "US.AAPL", PortfolioAssetClass.EQUITY, -1.0, "USD", -100.0),
        ),
    )
    rates = FXReferenceRateBatch("fixture", "SGD", (FXReferenceRate("USD", "SGD", 1.34, captured_at),))

    assert enforce_asset_class_exposure_limits(
        snapshot,
        rates,
        (AssetClassExposureLimit(PortfolioAssetClass.CRYPTO, 300.0), AssetClassExposureLimit(PortfolioAssetClass.EQUITY, 150.0)),
    ) is None


def test_asset_class_exposure_limits_fail_closed_for_missing_or_exceeded_caps():
    captured_at = datetime(2026, 7, 14, 12, tzinfo=UTC)
    snapshot = PortfolioSnapshot(
        "moomoo", "100", captured_at, (PortfolioHolding("100", "btc", "BTC", PortfolioAssetClass.CRYPTO, 1.0, "USD", 200.0),)
    )
    rates = FXReferenceRateBatch("fixture", "SGD", (FXReferenceRate("USD", "SGD", 1.34, captured_at),))

    with pytest.raises(ValueError, match="missing"):
        enforce_asset_class_exposure_limits(snapshot, rates, ())
    with pytest.raises(ValueError, match="exceeded"):
        enforce_asset_class_exposure_limits(snapshot, rates, (AssetClassExposureLimit(PortfolioAssetClass.CRYPTO, 200.0),))
