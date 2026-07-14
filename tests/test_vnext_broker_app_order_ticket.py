from datetime import UTC, datetime, timedelta

import pytest

from stonks_cli.vnext.broker_app_order_ticket import render_broker_app_order_ticket
from stonks_cli.vnext.reviewed_order_ticket import OrderTicketSide, OrderTicketType, ReviewedOrderTicket


def _ticket() -> ReviewedOrderTicket:
    prepared_at = datetime(2026, 7, 14, 12, tzinfo=UTC)
    return ReviewedOrderTicket(
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


def test_broker_app_order_ticket_renders_deterministic_manual_handoff_without_submission():
    rendered = render_broker_app_order_ticket(_ticket())

    assert rendered == "\n".join(
        (
            "MANUAL BROKER-APP ORDER TICKET",
            'ticket_id: "ticket-1"',
            'account_id: "100"',
            'symbol: "US.AAPL"',
            "side: BUY",
            "order_type: LIMIT",
            "quantity: 2.0",
            "limit_price: 200.0 USD",
            'rationale: "rebalance to approved target weight"',
            "prepared_at: 2026-07-14T12:00:00Z",
            'reviewed_by: "operator@example.test"',
            "reviewed_at: 2026-07-14T12:01:00Z",
            "submission: manual broker-app entry only; no API call made",
        )
    )


def test_broker_app_order_ticket_fails_closed_for_non_reviewed_ticket():
    with pytest.raises(TypeError, match="requires a reviewed order ticket"):
        render_broker_app_order_ticket(None)
