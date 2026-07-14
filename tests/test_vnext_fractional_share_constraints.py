from datetime import UTC, datetime, timedelta

import pytest

from stonks_cli.vnext.fractional_share_constraints import (
    FractionalShareEligibility,
    validate_fractional_share_constraints,
)
from stonks_cli.vnext.reviewed_order_ticket import OrderTicketSide, OrderTicketType, ReviewedOrderTicket


def _ticket(quantity: float) -> ReviewedOrderTicket:
    prepared_at = datetime(2026, 7, 14, 12, tzinfo=UTC)
    return ReviewedOrderTicket(
        "ticket-1",
        "100",
        "US.AAPL",
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


def test_fractional_share_constraints_allow_eligible_minimum_increment_quantity():
    eligibility = (FractionalShareEligibility("US.AAPL", True, 0.001, 0.001),)

    assert validate_fractional_share_constraints(_ticket(0.125), eligibility) is None


def test_fractional_share_constraints_fail_closed_for_missing_ineligible_or_invalid_increments():
    eligibility = (FractionalShareEligibility("US.AAPL", True, 0.001, 0.001),)

    with pytest.raises(ValueError, match="violates increment"):
        validate_fractional_share_constraints(_ticket(0.1255), eligibility)
    with pytest.raises(ValueError, match="missing"):
        validate_fractional_share_constraints(_ticket(0.125), ())
    with pytest.raises(ValueError, match="not eligible"):
        validate_fractional_share_constraints(_ticket(0.125), (FractionalShareEligibility("US.AAPL", False, None, None),))
    with pytest.raises(ValueError, match="integral increment"):
        FractionalShareEligibility("US.AAPL", True, 0.0015, 0.001)
