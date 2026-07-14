from datetime import UTC, datetime, timedelta

import pytest

from stonks_cli.vnext.exchange_lot_size import validate_exchange_lot_size
from stonks_cli.vnext.moomoo import MoomooInstrument
from stonks_cli.vnext.reviewed_order_ticket import OrderTicketSide, OrderTicketType, ReviewedOrderTicket


def _ticket(symbol: str, quantity: float) -> ReviewedOrderTicket:
    prepared_at = datetime(2026, 7, 14, 12, tzinfo=UTC)
    return ReviewedOrderTicket(
        "ticket-1",
        "100",
        symbol,
        OrderTicketSide.BUY,
        OrderTicketType.LIMIT,
        quantity,
        200.0,
        "USD",
        "rebalance to approved target weight",
        prepared_at,
        "operator@example.test",
        prepared_at + timedelta(minutes=1),
    )


def test_exchange_lot_size_validates_an_exact_active_instrument_lot_multiple():
    instruments = (MoomooInstrument("SG.D05", "DBS", 100, "STOCK", False),)

    assert validate_exchange_lot_size(_ticket("SG.D05", 200.0), instruments) is None


def test_exchange_lot_size_fails_closed_for_missing_suspended_or_non_integral_lots():
    instruments = (MoomooInstrument("SG.D05", "DBS", 100, "STOCK", False),)

    with pytest.raises(ValueError, match="integral lot"):
        validate_exchange_lot_size(_ticket("SG.D05", 150.0), instruments)
    with pytest.raises(ValueError, match="missing"):
        validate_exchange_lot_size(_ticket("US.AAPL", 1.0), instruments)
    with pytest.raises(ValueError, match="suspended"):
        validate_exchange_lot_size(_ticket("SG.D05", 100.0), (MoomooInstrument("SG.D05", "DBS", 100, "STOCK", True),))
