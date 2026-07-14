from datetime import UTC, date, datetime

import pytest

from stonks_cli.vnext.cash_ledger import CashLedger, CashLedgerEntry
from stonks_cli.vnext.fx_reference_rates import FXReferenceRate, FXReferenceRateBatch
from stonks_cli.vnext.portfolio_domain import PortfolioAssetClass, PortfolioHolding, PortfolioSnapshot
from stonks_cli.vnext.usd_portfolio_nav import calculate_usd_portfolio_nav


def test_usd_portfolio_nav_converts_holdings_and_cash_with_complete_direct_rates():
    captured_at = datetime(2026, 7, 14, 12, tzinfo=UTC)
    snapshot = PortfolioSnapshot(
        "moomoo",
        "100",
        captured_at,
        (
            PortfolioHolding("100", "sg", "SG.D05", PortfolioAssetClass.EQUITY, 1.0, "SGD", 100.0),
            PortfolioHolding("100", "us", "US.AAPL", PortfolioAssetClass.EQUITY, 2.0, "USD", 400.0),
        ),
    )
    ledger = CashLedger(
        "moomoo",
        "100",
        captured_at,
        (CashLedgerEntry("100", "sgd", date(2026, 7, 14), "SGD", -5.0, "fee"), CashLedgerEntry("100", "usd", date(2026, 7, 14), "USD", 10.0, "deposit")),
    )
    rates = FXReferenceRateBatch("fixture", "USD", (FXReferenceRate("SGD", "USD", 0.75, captured_at),))

    nav = calculate_usd_portfolio_nav(snapshot, ledger, rates)

    assert nav.holdings_value_usd == pytest.approx(475.0)
    assert nav.cash_value_usd == pytest.approx(6.25)
    assert nav.net_asset_value_usd == pytest.approx(481.25)


def test_usd_portfolio_nav_fails_closed_for_missing_rates_or_incoherent_snapshots():
    captured_at = datetime(2026, 7, 14, 12, tzinfo=UTC)
    snapshot = PortfolioSnapshot(
        "moomoo", "100", captured_at, (PortfolioHolding("100", "sg", "SG.D05", PortfolioAssetClass.EQUITY, 1.0, "SGD", 100.0),)
    )
    rates = FXReferenceRateBatch("fixture", "USD", (FXReferenceRate("EUR", "USD", 1.1, captured_at),))
    ledger = CashLedger("moomoo", "100", captured_at, ())

    with pytest.raises(ValueError, match="missing FX"):
        calculate_usd_portfolio_nav(snapshot, ledger, rates)
    with pytest.raises(ValueError, match="timestamps differ"):
        calculate_usd_portfolio_nav(snapshot, CashLedger("moomoo", "100", datetime(2026, 7, 14, 13, tzinfo=UTC), ()), rates)
