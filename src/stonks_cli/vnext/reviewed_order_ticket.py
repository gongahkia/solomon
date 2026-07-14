from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from stonks_cli.vnext.foundation import as_utc

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")


class OrderTicketSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderTicketType(StrEnum):
    LIMIT = "limit"


@dataclass(frozen=True)
class ReviewedOrderTicket:
    ticket_id: str
    account_id: str
    symbol: str
    side: OrderTicketSide
    order_type: OrderTicketType
    quantity: float
    limit_price: float
    currency: str
    rationale: str
    prepared_at: datetime
    reviewed_by: str
    reviewed_at: datetime

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.ticket_id, self.account_id, self.symbol, self.rationale, self.reviewed_by)):
            raise ValueError("reviewed order-ticket text fields are invalid")
        if not isinstance(self.side, OrderTicketSide) or not isinstance(self.order_type, OrderTicketType):
            raise ValueError("reviewed order-ticket side or type is invalid")
        if not isinstance(self.quantity, float) or not math.isfinite(self.quantity) or self.quantity <= 0:
            raise ValueError("reviewed order-ticket quantity is invalid")
        if not isinstance(self.limit_price, float) or not math.isfinite(self.limit_price) or self.limit_price <= 0:
            raise ValueError("reviewed order-ticket limit price is invalid")
        if not isinstance(self.currency, str) or not _CURRENCY_PATTERN.fullmatch(self.currency):
            raise ValueError("reviewed order-ticket currency is invalid")
        prepared_at = as_utc(self.prepared_at)
        reviewed_at = as_utc(self.reviewed_at)
        if reviewed_at < prepared_at:
            raise ValueError("reviewed order-ticket review precedes preparation")
        object.__setattr__(self, "prepared_at", prepared_at)
        object.__setattr__(self, "reviewed_at", reviewed_at)
