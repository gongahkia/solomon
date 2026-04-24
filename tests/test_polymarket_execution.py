from __future__ import annotations

import pytest

from stonks_cli.polymarket.execution import ExecutionOrder, _cancel_live_order, _extract_live_order_id, validate_execution_order


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


def test_extract_live_order_id_supports_dict_and_object():
    class _Resp:
        orderId = "abc-123"

    assert _extract_live_order_id({"orderID": "dict-1"}) == "dict-1"
    assert _extract_live_order_id(_Resp()) == "abc-123"


def test_cancel_live_order_falls_back_across_supported_methods():
    class _Client:
        def __init__(self):
            self.calls: list[tuple[str, object]] = []

        def cancel(self, *, order_id):
            raise TypeError("wrong signature here")

        def cancel_order(self, *, order_id):
            self.calls.append(("cancel_order", order_id))
            return {"ok": True}

    client = _Client()

    result = _cancel_live_order(client, "order-1")

    assert result == {"ok": True}
    assert client.calls == [("cancel_order", "order-1")]
