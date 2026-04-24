from __future__ import annotations

import pytest

from stonks_cli.polymarket.execution import ExecutionOrder, validate_execution_order


def test_validate_execution_order_rejects_invalid_price():
    with pytest.raises(ValueError):
        validate_execution_order(
            ExecutionOrder(
                token_id="YES1",
                market_id="1",
                slug="market-1",
                outcome="YES",
                side="BUY",
                price=1.0,
                shares=10,
            )
        )


def test_validate_execution_order_accepts_valid_order():
    validate_execution_order(
        ExecutionOrder(
            token_id="YES1",
            market_id="1",
            slug="market-1",
            outcome="YES",
            side="BUY",
            price=0.55,
            shares=10,
        )
    )
