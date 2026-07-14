from datetime import UTC, datetime, timedelta

import pytest

from stonks_cli.vnext.cost_basis import calculate_cost_basis
from stonks_cli.vnext.transactions_import import PortfolioTransaction, PortfolioTransactionSide


def test_cost_basis_calculates_moving_average_for_buy_and_sell_transactions():
    start = datetime(2026, 7, 14, tzinfo=UTC)
    transactions = (
        PortfolioTransaction("100", "buy-one", "US.AAPL", PortfolioTransactionSide.BUY, 2.0, 10.0, "USD", start),
        PortfolioTransaction("100", "buy-two", "US.AAPL", PortfolioTransactionSide.BUY, 2.0, 20.0, "USD", start + timedelta(minutes=1)),
        PortfolioTransaction("100", "sell", "US.AAPL", PortfolioTransactionSide.SELL, 1.0, 30.0, "USD", start + timedelta(minutes=2)),
    )

    basis = calculate_cost_basis(tuple(reversed(transactions)))

    assert basis[0].quantity == 3.0
    assert basis[0].total_cost == 45.0
    assert basis[0].average_unit_cost == 15.0


def test_cost_basis_fails_closed_for_oversells_short_transactions_or_duplicate_ids():
    timestamp = datetime(2026, 7, 14, tzinfo=UTC)
    buy = PortfolioTransaction("100", "buy", "US.AAPL", PortfolioTransactionSide.BUY, 1.0, 10.0, "USD", timestamp)
    oversell = PortfolioTransaction("100", "sell", "US.AAPL", PortfolioTransactionSide.SELL, 2.0, 10.0, "USD", timestamp + timedelta(minutes=1))
    short = PortfolioTransaction("100", "short", "US.AAPL", PortfolioTransactionSide.SELL_SHORT, 1.0, 10.0, "USD", timestamp)
    duplicate = PortfolioTransaction("100", "buy", "US.MSFT", PortfolioTransactionSide.BUY, 1.0, 10.0, "USD", timestamp)

    with pytest.raises(ValueError, match="sells more"):
        calculate_cost_basis((buy, oversell))
    with pytest.raises(ValueError, match="short"):
        calculate_cost_basis((short,))
    with pytest.raises(ValueError, match="unique"):
        calculate_cost_basis((buy, duplicate))
