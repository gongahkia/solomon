from __future__ import annotations

import json

from stonks_cli.vnext.reviewed_order_ticket import ReviewedOrderTicket


def render_broker_app_order_ticket(ticket: ReviewedOrderTicket) -> str:
    if not isinstance(ticket, ReviewedOrderTicket):
        raise TypeError("broker-app order-ticket rendering requires a reviewed order ticket")
    return "\n".join(
        (
            "MANUAL BROKER-APP ORDER TICKET",
            f"ticket_id: {_render_text(ticket.ticket_id)}",
            f"account_id: {_render_text(ticket.account_id)}",
            f"symbol: {_render_text(ticket.symbol)}",
            f"side: {ticket.side.value.upper()}",
            f"order_type: {ticket.order_type.value.upper()}",
            f"quantity: {ticket.quantity!r}",
            f"limit_price: {ticket.limit_price!r} {ticket.currency}",
            f"rationale: {_render_text(ticket.rationale)}",
            f"prepared_at: {ticket.prepared_at.isoformat().replace('+00:00', 'Z')}",
            f"reviewed_by: {_render_text(ticket.reviewed_by)}",
            f"reviewed_at: {ticket.reviewed_at.isoformat().replace('+00:00', 'Z')}",
            "submission: manual broker-app entry only; no API call made",
        )
    )


def _render_text(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)
