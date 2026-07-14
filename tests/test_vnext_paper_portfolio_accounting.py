from datetime import UTC, datetime, timedelta

import pytest

from stonks_cli.vnext.paper_portfolio_accounting import (
    PaperPortfolioAccount,
    PaperPortfolioPosition,
    run_paper_portfolio_accounting,
)
from stonks_cli.vnext.reviewed_order_ticket import OrderTicketSide, OrderTicketType, ReviewedOrderTicket


def _ticket(ticket_id: str, side: OrderTicketSide, symbol: str, quantity: float, limit_price: float, minutes: int) -> ReviewedOrderTicket:
    prepared_at = datetime(2026, 7, 14, 12, tzinfo=UTC) + timedelta(minutes=minutes)
    return ReviewedOrderTicket(
        ticket_id,
        "100",
        symbol,
        side,
        OrderTicketType.LIMIT,
        quantity,
        limit_price,
        "USD",
        "rebalance to approved target weight",
        prepared_at,
        "operator@example.test",
        prepared_at + timedelta(seconds=1),
    )


def test_paper_portfolio_accounting_applies_canonical_reviewed_tickets_to_cash_and_long_positions():
    account = PaperPortfolioAccount("100", "USD", 1000.0, (PaperPortfolioPosition("US.MSFT", 1.0),))
    tickets = (
        _ticket("ticket-buy", OrderTicketSide.BUY, "US.AAPL", 2.0, 200.0, 0),
        _ticket("ticket-sell", OrderTicketSide.SELL, "US.MSFT", 1.0, 250.0, 1),
    )

    updated = run_paper_portfolio_accounting(account, tickets)

    assert updated.cash_balance == 850.0
    assert updated.positions == (PaperPortfolioPosition("US.AAPL", 2.0),)
    assert updated.applied_ticket_ids == ("ticket-buy", "ticket-sell")


def test_paper_portfolio_accounting_fails_closed_for_insufficient_or_duplicate_tickets():
    account = PaperPortfolioAccount("100", "USD", 100.0, ())
    ticket = _ticket("ticket-buy", OrderTicketSide.BUY, "US.AAPL", 1.0, 200.0, 0)

    with pytest.raises(ValueError, match="cash is insufficient"):
        run_paper_portfolio_accounting(account, (ticket,))
    with pytest.raises(ValueError, match="already applied"):
        run_paper_portfolio_accounting(PaperPortfolioAccount("100", "USD", 1000.0, (), ("ticket-buy",)), (ticket,))
    with pytest.raises(ValueError, match="position is insufficient"):
        run_paper_portfolio_accounting(account, (_ticket("ticket-sell", OrderTicketSide.SELL, "US.AAPL", 1.0, 200.0, 0),))
