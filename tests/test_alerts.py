from __future__ import annotations

from datetime import date
from decimal import Decimal

from stonks_cli.alerts import price_move_alert


def test_price_move_alert_requires_two_prices_and_honours_threshold() -> None:
    prices = ((date(2026, 1, 1), Decimal("100")), (date(2026, 1, 2), Decimal("106")))

    assert price_move_alert("US:SPY", prices[:1], Decimal("5")) is None
    alert = price_move_alert("US:SPY", prices, Decimal("5"))
    assert alert is not None
    assert alert.change_percent == Decimal("6.00")
