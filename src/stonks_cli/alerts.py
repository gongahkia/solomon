from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class PriceMoveAlert:
    instrument_key: str
    as_of: date
    previous_close: Decimal
    close: Decimal
    change: Decimal

    @property
    def change_percent(self) -> Decimal:
        return self.change / self.previous_close * Decimal("100")


def price_move_alert(
    instrument_key: str,
    prices: tuple[tuple[date, Decimal], ...],
    threshold_percent: Decimal,
) -> PriceMoveAlert | None:
    if threshold_percent < 0:
        raise ValueError("alert threshold must be non-negative")
    if len(prices) < 2:
        return None
    previous_date, previous_close = prices[-2]
    current_date, close = prices[-1]
    if previous_date >= current_date or previous_close <= 0:
        raise ValueError("alert prices must be strictly chronological and positive")
    alert = PriceMoveAlert(instrument_key, current_date, previous_close, close, close - previous_close)
    return alert if abs(alert.change_percent) >= threshold_percent else None
