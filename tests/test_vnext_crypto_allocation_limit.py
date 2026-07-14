from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.crypto_allocation_limit import enforce_crypto_allocation_limit
from stonks_cli.vnext.fx_reference_rates import FXReferenceRate, FXReferenceRateBatch
from stonks_cli.vnext.portfolio_domain import PortfolioAssetClass, PortfolioHolding, PortfolioSnapshot


def test_crypto_allocation_limit_enforces_converted_gross_weight_inclusively():
    captured_at = datetime(2026, 7, 14, 12, tzinfo=UTC)
    snapshot = PortfolioSnapshot(
        "moomoo",
        "100",
        captured_at,
        (
            PortfolioHolding("100", "btc", "BTC", PortfolioAssetClass.CRYPTO, 1.0, "USD", 200.0),
            PortfolioHolding("100", "sg", "SG.D05", PortfolioAssetClass.EQUITY, 1.0, "SGD", 800.0),
        ),
    )
    rates = FXReferenceRateBatch("fixture", "USD", (FXReferenceRate("SGD", "USD", 0.75, captured_at),))

    assert enforce_crypto_allocation_limit(snapshot, rates, 0.25) is None

    with pytest.raises(ValueError, match="exceeded"):
        enforce_crypto_allocation_limit(snapshot, rates, 0.249)


def test_crypto_allocation_limit_fails_closed_for_missing_rates_empty_portfolios_and_invalid_limits():
    captured_at = datetime(2026, 7, 14, 12, tzinfo=UTC)
    snapshot = PortfolioSnapshot(
        "moomoo", "100", captured_at, (PortfolioHolding("100", "btc", "BTC", PortfolioAssetClass.CRYPTO, 1.0, "USD", 200.0),)
    )
    missing_rates = FXReferenceRateBatch("fixture", "SGD", (FXReferenceRate("EUR", "SGD", 1.5, captured_at),))

    with pytest.raises(ValueError, match="missing FX"):
        enforce_crypto_allocation_limit(snapshot, missing_rates, 1.0)
    with pytest.raises(ValueError, match="portfolio value"):
        enforce_crypto_allocation_limit(PortfolioSnapshot("moomoo", "100", captured_at, ()), missing_rates, 1.0)
    with pytest.raises(ValueError, match="invalid"):
        enforce_crypto_allocation_limit(snapshot, missing_rates, 1.1)
