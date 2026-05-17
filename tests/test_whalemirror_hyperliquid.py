from __future__ import annotations

from decimal import Decimal

import pytest

from stonks_cli.whalemirror.hyperliquid import (
    HyperliquidCancelIntent,
    HyperliquidOrderClient,
    HyperliquidOrderIntent,
    HyperliquidSignature,
    LiveExecutionBlocked,
    build_cancel_action,
    build_open_orders_subscription,
    build_order_action,
    build_order_updates_subscription,
    build_ws_action_post_request,
    entry_price_guard_reasons,
)
from stonks_cli.whalemirror.models import MirrorMode


class _Response:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, *, json, timeout):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return _Response(self.response)


def _order() -> HyperliquidOrderIntent:
    return HyperliquidOrderIntent(
        asset_index=0,
        coin="BTC",
        is_buy=True,
        limit_px=Decimal("65000"),
        size=Decimal("0.01"),
        cloid="mirror-1",
    )


def test_build_order_action_matches_hyperliquid_shape():
    action = build_order_action(_order())

    assert action == {
        "type": "order",
        "orders": [
            {
                "a": 0,
                "b": True,
                "p": "65000",
                "s": "0.01",
                "r": False,
                "t": {"limit": {"tif": "Alo"}},
                "c": "mirror-1",
            }
        ],
        "grouping": "na",
    }


def test_build_cancel_action_supports_oid_and_cloid():
    action = build_cancel_action(
        [
            HyperliquidCancelIntent(asset_index=0, oid=123),
            HyperliquidCancelIntent(asset_index=1, cloid="mirror-2"),
        ]
    )

    assert action == {
        "type": "cancel",
        "cancels": [{"a": 0, "o": 123}, {"a": 1, "cloid": "mirror-2"}],
    }


def test_websocket_order_subscriptions_match_hyperliquid_shape():
    assert build_open_orders_subscription(user="0xABCDEF", dex="test") == {
        "method": "subscribe",
        "subscription": {"type": "openOrders", "user": "0xabcdef", "dex": "test"},
    }
    assert build_order_updates_subscription(user="0xABCDEF") == {
        "method": "subscribe",
        "subscription": {"type": "orderUpdates", "user": "0xabcdef"},
    }


def test_websocket_action_post_wraps_signed_order_payload():
    signature = HyperliquidSignature(r="0x1", s="0x2", v=27)

    request = build_ws_action_post_request(
        request_id=7,
        action=build_order_action(_order()),
        nonce=123456,
        signature=signature,
    )

    assert request == {
        "method": "post",
        "id": 7,
        "request": {
            "type": "action",
            "payload": {
                "action": build_order_action(_order()),
                "nonce": 123456,
                "signature": {"r": "0x1", "s": "0x2", "v": 27},
            },
        },
    }


def test_dry_run_create_order_does_not_submit():
    session = _Session({"status": "ok"})
    client = HyperliquidOrderClient(session=session)

    response = client.create_order(_order(), mode=MirrorMode.DRY_RUN)

    assert response["status"] == "dry_run"
    assert response["request"]["action"]["type"] == "order"
    assert session.calls == []


def test_live_create_order_fails_closed_without_arm(monkeypatch):
    monkeypatch.delenv("STONKS_CLI_HYPERLIQUID_LIVE_ARMED", raising=False)
    client = HyperliquidOrderClient(session=_Session({"status": "ok"}))

    with pytest.raises(LiveExecutionBlocked) as exc:
        client.create_order(
            _order(),
            mode=MirrorMode.LIVE,
            nonce=1,
            signature=HyperliquidSignature(r="0x1", s="0x2", v=27),
        )

    assert "live_trading_not_armed:STONKS_CLI_HYPERLIQUID_LIVE_ARMED" in exc.value.reasons


def test_live_create_order_requires_signed_payload_even_when_armed(monkeypatch):
    monkeypatch.setenv("STONKS_CLI_HYPERLIQUID_LIVE_ARMED", "armed")
    client = HyperliquidOrderClient(session=_Session({"status": "ok"}))

    with pytest.raises(LiveExecutionBlocked) as exc:
        client.create_order(_order(), mode=MirrorMode.LIVE)

    assert exc.value.reasons == ["missing_signed_hyperliquid_payload"]


def test_live_create_order_honors_runtime_guardrails(monkeypatch):
    monkeypatch.setenv("STONKS_CLI_HYPERLIQUID_LIVE_ARMED", "armed")
    client = HyperliquidOrderClient(session=_Session({"status": "ok"}))

    with pytest.raises(LiveExecutionBlocked) as exc:
        client.create_order(
            _order(),
            mode=MirrorMode.LIVE,
            nonce=1,
            signature=HyperliquidSignature(r="0x1", s="0x2", v=27),
            heartbeat_ok=False,
            emergency_stop_active=True,
            consensus_approved=False,
        )

    assert exc.value.reasons == [
        "heartbeat_not_fresh",
        "emergency_stop_active",
        "consensus_not_approved",
    ]


def test_live_create_order_posts_when_armed_and_signed(monkeypatch):
    monkeypatch.setenv("STONKS_CLI_HYPERLIQUID_LIVE_ARMED", "armed")
    session = _Session({"status": "ok", "response": {"type": "order", "data": {"statuses": ["success"]}}})
    client = HyperliquidOrderClient(session=session, exchange_url="https://example.test/exchange")

    response = client.create_order(
        _order(),
        mode=MirrorMode.LIVE,
        nonce=123456,
        signature=HyperliquidSignature(r="0x1", s="0x2", v=27),
    )

    assert response["status"] == "ok"
    assert session.calls[0]["url"] == "https://example.test/exchange"
    assert session.calls[0]["json"]["action"]["type"] == "order"


def test_live_ws_order_post_uses_same_guards_and_signed_payload(monkeypatch):
    monkeypatch.setenv("STONKS_CLI_HYPERLIQUID_LIVE_ARMED", "armed")
    client = HyperliquidOrderClient(session=_Session({"status": "ok"}))

    request = client.build_ws_order_post(
        _order(),
        request_id=9,
        mode=MirrorMode.LIVE,
        nonce=123456,
        signature=HyperliquidSignature(r="0x1", s="0x2", v=27),
        heartbeat_ok=True,
        consensus_approved=True,
    )

    assert request["method"] == "post"
    assert request["id"] == 9
    assert request["request"]["type"] == "action"
    assert request["request"]["payload"]["action"]["type"] == "order"


def test_sync_open_orders_parses_fixture_payload():
    session = _Session(
        [
            {
                "coin": "BTC",
                "side": "A",
                "limitPx": "43250.0",
                "sz": "0.5",
                "oid": 127244980388,
                "timestamp": 1681923833000,
                "origSz": "1.0",
                "cloid": "mirror-1",
            }
        ]
    )
    client = HyperliquidOrderClient(session=session, info_url="https://example.test/info")

    orders = client.sync_open_orders(user="0xABCDEF")

    assert len(orders) == 1
    assert orders[0].coin == "BTC"
    assert orders[0].limit_px == Decimal("43250.0")
    assert session.calls[0]["json"] == {"type": "openOrders", "user": "0xabcdef"}


def test_entry_price_guard_blocks_aggressive_orders():
    reasons = entry_price_guard_reasons(order=_order(), mark_px=Decimal("60000"), max_slippage_bps=Decimal("100"))

    assert reasons == ["entry_price_above_mark_guard:65000>60600"]
