from datetime import UTC, datetime, timedelta

import pytest

from stonks_cli.vnext.reviewed_order_ticket import OrderTicketSide, OrderTicketType, ReviewedOrderTicket


def test_reviewed_order_ticket_preserves_a_reviewed_limit_order_without_submission_capability():
    prepared_at = datetime(2026, 7, 14, 12, tzinfo=UTC)

    ticket = ReviewedOrderTicket(
        "ticket-1",
        "100",
        "US.AAPL",
        OrderTicketSide.BUY,
        OrderTicketType.LIMIT,
        2.0,
        200.0,
        "USD",
        "rebalance to approved target weight",
        prepared_at,
        "operator@example.test",
        prepared_at + timedelta(minutes=1),
    )

    assert ticket.side is OrderTicketSide.BUY
    assert ticket.order_type is OrderTicketType.LIMIT
    assert ticket.reviewed_at == prepared_at + timedelta(minutes=1)
    assert not hasattr(ticket, "submit")


def test_reviewed_order_ticket_fails_closed_for_unreviewed_or_malformed_values():
    prepared_at = datetime(2026, 7, 14, 12, tzinfo=UTC)
    values = ("ticket-1", "100", "US.AAPL", OrderTicketSide.BUY, OrderTicketType.LIMIT, 2.0, 200.0, "USD", "reason", prepared_at, "operator")

    with pytest.raises(ValueError, match="text fields"):
        ReviewedOrderTicket(*values[:-1], "", prepared_at)
    with pytest.raises(ValueError, match="review precedes"):
        ReviewedOrderTicket(*values, prepared_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match="quantity"):
        ReviewedOrderTicket(*values[:5], 0.0, *values[6:], prepared_at)
