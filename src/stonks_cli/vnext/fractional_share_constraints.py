from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from stonks_cli.vnext.reviewed_order_ticket import ReviewedOrderTicket


@dataclass(frozen=True)
class FractionalShareEligibility:
    symbol: str
    is_eligible: bool
    minimum_quantity: float | None
    quantity_increment: float | None

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol or not isinstance(self.is_eligible, bool):
            raise ValueError("fractional-share eligibility fields are invalid")
        if not self.is_eligible:
            if self.minimum_quantity is not None or self.quantity_increment is not None:
                raise ValueError("ineligible fractional-share fields must be absent")
            return
        if not all(
            isinstance(value, float) and math.isfinite(value) and value > 0
            for value in (self.minimum_quantity, self.quantity_increment)
        ):
            raise ValueError("fractional-share constraints are invalid")
        if not _is_integral_increment(self.minimum_quantity, self.quantity_increment):
            raise ValueError("fractional-share minimum is not an integral increment")


def validate_fractional_share_constraints(
    ticket: ReviewedOrderTicket, eligibility: tuple[FractionalShareEligibility, ...]
) -> None:
    if not isinstance(ticket, ReviewedOrderTicket):
        raise TypeError("fractional-share validation requires a reviewed order ticket")
    if not isinstance(eligibility, tuple) or not all(isinstance(item, FractionalShareEligibility) for item in eligibility):
        raise ValueError("fractional-share eligibility is invalid")
    symbols = tuple(item.symbol for item in eligibility)
    if len(set(symbols)) != len(symbols) or symbols != tuple(sorted(symbols)):
        raise ValueError("fractional-share eligibility is not canonical")
    if ticket.quantity.is_integer():
        return
    constraint = next((item for item in eligibility if item.symbol == ticket.symbol), None)
    if constraint is None:
        raise ValueError(f"fractional-share eligibility is missing:{ticket.symbol}")
    if not constraint.is_eligible:
        raise ValueError(f"fractional shares are not eligible:{ticket.symbol}")
    if ticket.quantity < constraint.minimum_quantity:
        raise ValueError(f"fractional-share quantity is below minimum:{ticket.symbol}")
    if not _is_integral_increment(ticket.quantity, constraint.quantity_increment):
        raise ValueError(f"fractional-share quantity violates increment:{ticket.symbol}")


def _is_integral_increment(quantity: float, increment: float) -> bool:
    lots = Decimal(str(quantity)) / Decimal(str(increment))
    return lots == lots.to_integral_value()
