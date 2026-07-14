from datetime import UTC, date, datetime

import pytest

from stonks_cli.vnext.cash_ledger import CashLedger, CashLedgerEntry
from stonks_cli.vnext.fx_reference_rates import FXReferenceRate, FXReferenceRateBatch
from stonks_cli.vnext.portfolio_domain import PortfolioAssetClass, PortfolioHolding, PortfolioSnapshot
from stonks_cli.vnext.portfolio_exposure import calculate_portfolio_exposure
from stonks_cli.vnext.usd_portfolio_nav import calculate_usd_portfolio_nav


def test_portfolio_exposure_and_usd_nav_preserve_signed_value_invariants():
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
    ledger = CashLedger(
        "moomoo",
        "100",
        captured_at,
        (
            CashLedgerEntry("100", "sgd-fee", date(2026, 7, 14), "SGD", -5.0, "fee"),
            CashLedgerEntry("100", "usd-deposit", date(2026, 7, 14), "USD", 10.0, "deposit"),
        ),
    )
    rates = FXReferenceRateBatch("fixture", "USD", (FXReferenceRate("SGD", "USD", 0.75, captured_at),))

    exposure = calculate_portfolio_exposure(snapshot, rates)
    nav = calculate_usd_portfolio_nav(snapshot, ledger, rates)

    assert exposure.gross_exposure == pytest.approx(exposure.long_exposure + exposure.short_exposure)
    assert exposure.net_exposure == pytest.approx(exposure.long_exposure - exposure.short_exposure)
    assert exposure.gross_exposure >= abs(exposure.net_exposure)
    assert nav.holdings_value_usd == pytest.approx(exposure.net_exposure)
    assert nav.net_asset_value_usd == pytest.approx(nav.holdings_value_usd + nav.cash_value_usd)
