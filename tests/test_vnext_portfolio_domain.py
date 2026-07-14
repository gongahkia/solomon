from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.portfolio_domain import PortfolioAssetClass, PortfolioHolding, PortfolioSnapshot


def test_portfolio_snapshot_preserves_canonical_signed_holdings():
    apple = PortfolioHolding("100", "apple", "US.AAPL", PortfolioAssetClass.EQUITY, 2.0, "USD", 400.0)
    bitcoin = PortfolioHolding("100", "bitcoin", "BTC", PortfolioAssetClass.CRYPTO, 0.1, "USD", 6_000.0)

    snapshot = PortfolioSnapshot("moomoo", "100", datetime(2026, 7, 14, 12, tzinfo=UTC), (bitcoin, apple))

    assert snapshot.holdings == (bitcoin, apple)


@pytest.mark.parametrize(
    "holding",
    (
        ("100", "apple", "US.AAPL", PortfolioAssetClass.EQUITY, 0.0, "USD", 400.0),
        ("100", "apple", "US.AAPL", PortfolioAssetClass.EQUITY, 2.0, "usd", 400.0),
        ("100", "apple", "US.AAPL", PortfolioAssetClass.EQUITY, -2.0, "USD", 400.0),
    ),
)
def test_portfolio_domain_fails_closed_for_invalid_holdings_or_snapshots(holding):
    with pytest.raises(ValueError):
        PortfolioHolding(*holding)

    apple = PortfolioHolding("100", "apple", "US.AAPL", PortfolioAssetClass.EQUITY, 2.0, "USD", 400.0)
    with pytest.raises(ValueError, match="different account"):
        PortfolioSnapshot("moomoo", "other", datetime(2026, 7, 14, 12, tzinfo=UTC), (apple,))
    with pytest.raises(ValueError, match="unique"):
        PortfolioSnapshot("moomoo", "100", datetime(2026, 7, 14, 12, tzinfo=UTC), (apple, apple))
    microsoft = PortfolioHolding("100", "microsoft", "US.MSFT", PortfolioAssetClass.EQUITY, 2.0, "USD", 800.0)
    with pytest.raises(ValueError, match="canonical"):
        PortfolioSnapshot("moomoo", "100", datetime(2026, 7, 14, 12, tzinfo=UTC), (microsoft, apple))
