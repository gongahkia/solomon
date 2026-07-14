from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from stonks_cli.research.hyperliquid import (
    HyperliquidCancelIntent,
    HyperliquidCarryInput,
    HyperliquidOrderClient,
    HyperliquidOrderIntent,
    HyperliquidSignature,
    LiveExecutionBlocked,
    blocked_carry_opportunity,
    build_cancel_action,
    build_open_orders_subscription,
    build_order_action,
    build_order_updates_subscription,
    build_ws_action_post_request,
    entry_price_guard_reasons,
    validate_carry_input_completeness,
)
from stonks_cli.research.models import ExecutionMode


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


class _SequenceSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, *, json, timeout):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return _Response(self.responses.pop(0))


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

    response = client.create_order(_order(), mode=ExecutionMode.DRY_RUN)

    assert response["status"] == "dry_run"
    assert response["request"]["action"]["type"] == "order"
    assert session.calls == []


def test_live_create_order_fails_closed_without_arm(monkeypatch):
    monkeypatch.delenv("STONKS_CLI_HYPERLIQUID_LIVE_ARMED", raising=False)
    client = HyperliquidOrderClient(session=_Session({"status": "ok"}))

    with pytest.raises(LiveExecutionBlocked) as exc:
        client.create_order(
            _order(),
            mode=ExecutionMode.LIVE,
            nonce=1,
            signature=HyperliquidSignature(r="0x1", s="0x2", v=27),
        )

    assert "live_trading_not_armed:STONKS_CLI_HYPERLIQUID_LIVE_ARMED" in exc.value.reasons


def test_live_create_order_requires_signed_payload_even_when_armed(monkeypatch):
    monkeypatch.setenv("STONKS_CLI_HYPERLIQUID_LIVE_ARMED", "armed")
    client = HyperliquidOrderClient(session=_Session({"status": "ok"}))

    with pytest.raises(LiveExecutionBlocked) as exc:
        client.create_order(_order(), mode=ExecutionMode.LIVE)

    assert exc.value.reasons == ["missing_signed_hyperliquid_payload"]


def test_live_create_order_honors_runtime_guardrails(monkeypatch):
    monkeypatch.setenv("STONKS_CLI_HYPERLIQUID_LIVE_ARMED", "armed")
    client = HyperliquidOrderClient(session=_Session({"status": "ok"}))

    with pytest.raises(LiveExecutionBlocked) as exc:
        client.create_order(
            _order(),
            mode=ExecutionMode.LIVE,
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
        mode=ExecutionMode.LIVE,
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
        mode=ExecutionMode.LIVE,
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


def test_fetch_hyperliquid_carry_inputs_includes_btc_eth_sources():
    session = _SequenceSession(_carry_source_responses())
    client = HyperliquidOrderClient(session=session, info_url="https://example.test/info")

    inputs = client.fetch_carry_inputs(timestamp_utc="2026-07-02T00:00:00Z")

    assert [call["json"]["type"] for call in session.calls] == [
        "allMids",
        "metaAndAssetCtxs",
        "spotMetaAndAssetCtxs",
        "predictedFundings",
    ]
    assert [row.asset for row in inputs] == ["BTC", "ETH"]
    assert inputs[0].quote.spot_mid == 100000.0
    assert inputs[0].quote.perp_mid == 100100.0
    assert inputs[0].quote.mark_mid == 100090.0
    assert inputs[0].quote.oracle_mid == 100050.0
    assert inputs[0].funding is not None
    assert inputs[0].funding.hourly_rate == 0.0001
    assert inputs[0].basis is not None
    assert inputs[0].metadata["perp"]["maxLeverage"] == 50
    assert inputs[0].metadata["spot"]["name"] == "BTC/USDC"
    assert inputs[0].source_health["predicted_funding"] == "ok"


def test_fetch_funding_history_uses_official_info_request_shape():
    session = _Session([{"coin": "BTC", "fundingRate": "0.0001", "time": 1770000000000}])
    client = HyperliquidOrderClient(session=session, info_url="https://example.test/info")

    rows = client.fetch_funding_history(coin="BTC", start_time=1770000000000, end_time=1770003600000)

    assert rows[0]["coin"] == "BTC"
    assert session.calls[0]["json"] == {
        "type": "fundingHistory",
        "coin": "BTC",
        "startTime": 1770000000000,
        "endTime": 1770003600000,
    }


def test_carry_input_completeness_reports_missing_fields_as_opportunity_caveats():
    inputs = _complete_carry_input()
    broken = replace(inputs, quote=replace(inputs.quote, spot_mid=None), basis=None)

    validation = validate_carry_input_completeness(
        broken,
        now=datetime(2026, 7, 2, 0, 0, 10, tzinfo=UTC),
    )
    blocked = blocked_carry_opportunity(broken, validation)

    assert validation.ok is False
    assert "quote.spot_mid" in validation.required_fields_missing
    assert "basis" in blocked.required_fields_missing
    assert blocked.direction == "blocked"


def test_carry_input_completeness_rejects_stale_inputs():
    inputs = _complete_carry_input(timestamp="2026-07-02T00:00:00Z")

    validation = validate_carry_input_completeness(
        inputs,
        now=datetime(2026, 7, 2, 0, 2, 0, tzinfo=UTC),
        max_age_seconds=30,
    )

    assert validation.ok is False
    assert "stale:quote:120s>30s" in validation.stale_fields
    assert "stale:funding:120s>30s" in validation.stale_fields


def test_carry_input_completeness_rejects_cross_timestamp_inputs():
    inputs = _complete_carry_input(timestamp="2026-07-02T00:00:00Z")
    assert inputs.funding is not None
    skewed = replace(inputs, funding=replace(inputs.funding, timestamp="2026-07-02T00:01:00Z"))

    validation = validate_carry_input_completeness(
        skewed,
        now=datetime(2026, 7, 2, 0, 1, 5, tzinfo=UTC),
        max_age_seconds=120,
        max_timestamp_skew_seconds=10,
    )

    assert validation.ok is False
    assert validation.cross_timestamp_fields == ["cross_timestamp:basis,funding,quote:60s>10s"]


def test_entry_price_guard_blocks_aggressive_orders():
    reasons = entry_price_guard_reasons(order=_order(), mark_px=Decimal("60000"), max_slippage_bps=Decimal("100"))

    assert reasons == ["entry_price_above_mark_guard:65000>60600"]


def _carry_source_responses():
    return [
        {"mids": {"BTC": "100100", "ETH": "3100", "BTC/USDC": "100000", "ETH/USDC": "3000"}},
        [
            {
                "universe": [
                    {"name": "BTC", "szDecimals": 5, "maxLeverage": 50},
                    {"name": "ETH", "szDecimals": 4, "maxLeverage": 50},
                ]
            },
            [
                {"markPx": "100090", "oraclePx": "100050", "funding": "0.0001", "premium": "0.001"},
                {"markPx": "3090", "oraclePx": "3050", "funding": "0.0002", "premium": "0.002"},
            ],
        ],
        [
            {
                "tokens": [
                    {"name": "USDC", "index": 0},
                    {"name": "BTC", "index": 1},
                    {"name": "ETH", "index": 2},
                ],
                "universe": [
                    {"name": "BTC/USDC", "tokens": [1, 0], "index": 0},
                    {"name": "ETH/USDC", "tokens": [2, 0], "index": 1},
                ],
            },
            [{"midPx": "100000"}, {"midPx": "3000"}],
        ],
        [["BTC", [["HlPerp", {"fundingRate": "0.00011"}]]], ["ETH", [["HlPerp", {"fundingRate": "0.00021"}]]]],
    ]


def _complete_carry_input(timestamp: str = "2026-07-02T00:00:00Z") -> HyperliquidCarryInput:
    session = _SequenceSession(_carry_source_responses())
    client = HyperliquidOrderClient(session=session, info_url="https://example.test/info")
    return client.fetch_carry_inputs(assets=("BTC",), timestamp_utc=timestamp)[0]
