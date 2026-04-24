from __future__ import annotations

import sys
import types

import pytest

from stonks_cli.config import AppConfig, PolymarketConfig
from stonks_cli.polymarket.execution import (
    ExecutionOrder,
    LiveExecutor,
    _cancel_live_order,
    _extract_live_order_id,
    validate_execution_order,
)
from stonks_cli.polymarket.models import BookLevel, OrderBook


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


def test_live_executor_uses_rust_hotpath_guard(monkeypatch, tmp_path):
    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=False, rust_hotpath_enabled=True))
    from stonks_cli.polymarket import lifecycle

    monkeypatch.setattr(lifecycle, "default_state_dir", lambda: tmp_path)

    class _Rust:
        def __init__(self):
            self.calls: list[tuple[str, object]] = []

        def update_book(self, **kwargs):
            self.calls.append(("update_book", kwargs))

        def guard_order(self, **kwargs):
            self.calls.append(("guard_order", kwargs))
            return {"price": "0.58", "shares": "7", "post_only": "true"}

        def stale_orders(self, *, max_age_s: int):
            self.calls.append(("stale_orders", max_age_s))
            return []

        def register_order(self, **kwargs):
            self.calls.append(("register_order", kwargs))
            return {"order_id": kwargs["order_id"]}

    rust = _Rust()
    monkeypatch.setattr("stonks_cli.polymarket.execution.rust_session", lambda cfg: rust)
    fake_sdk = types.ModuleType("py_clob_client_v2")

    class _Side:
        BUY = "BUY"
        SELL = "SELL"

    class _OrderArgs:
        def __init__(self, *, token_id, price, side, size):
            self.token_id = token_id
            self.price = price
            self.side = side
            self.size = size

    class _PartialCreateOrderOptions:
        def __init__(self, *, tick_size):
            self.tick_size = tick_size

    fake_sdk.ClobClient = object
    fake_sdk.OrderArgs = _OrderArgs
    fake_sdk.OrderType = types.SimpleNamespace(GTC="GTC")
    fake_sdk.PartialCreateOrderOptions = _PartialCreateOrderOptions
    fake_sdk.Side = _Side
    monkeypatch.setitem(sys.modules, "py_clob_client_v2", fake_sdk)

    class _Client:
        def create_and_post_order(self, *, order_args, options, order_type):
            assert order_args.price == 0.58
            assert order_args.size == 7.0
            return {"orderID": "live-1", "status": "live"}

    monkeypatch.setattr(LiveExecutor, "_build_client", lambda self: _Client())
    monkeypatch.setattr(
        "stonks_cli.polymarket.execution.PolymarketClient.get_book",
        lambda self, token_id: OrderBook(
            token_id=token_id,
            bids=[BookLevel(price=0.57, size=100.0)],
            asks=[BookLevel(price=0.60, size=100.0)],
            midpoint=0.585,
            best_bid=0.57,
            best_ask=0.60,
            raw={"tick_size": "0.01", "min_order_size": "5"},
        ),
    )
    monkeypatch.setattr("stonks_cli.polymarket.execution.authenticated_clob_client", lambda cfg: (_Client(), None))

    executor = LiveExecutor(cfg)
    result = executor.execute(
        ExecutionOrder(
            token_id="YES1",
            market_id="m1",
            slug="btc-higher",
            outcome="YES",
            side="BUY",
            price=0.581,
            shares=7,
        )
    )

    assert result["order_id"] == "live-1"
    assert ("stale_orders", cfg.polymarket.live_order_max_age_seconds) in rust.calls
    assert any(name == "guard_order" for name, _ in rust.calls)
    assert any(name == "register_order" for name, _ in rust.calls)
