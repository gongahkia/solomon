from __future__ import annotations

import asyncio
import json

import pytest

from stonks_cli.config import AppConfig, PolymarketConfig
from stonks_cli.polymarket.execution import ExecutionOrder
from stonks_cli.polymarket.lifecycle import LiveOrderManager, build_live_order_request
from stonks_cli.polymarket.models import LiveMarketSnapshot
from stonks_cli.polymarket.websocket import (
    MarketWebSocketClient,
    UserWebSocketClient,
    build_market_subscription,
    parse_ws_message,
)


def test_build_market_subscription_requires_assets():
    with pytest.raises(ValueError):
        build_market_subscription([])


def test_build_market_subscription_enables_custom_features():
    payload = build_market_subscription(["YES1"])

    assert payload["custom_feature_enabled"] is True


def test_parse_ws_message_accepts_single_and_batch_payloads():
    single = parse_ws_message('{"event_type":"best_bid_ask","asset_id":"YES1"}')
    batch = parse_ws_message(
        json.dumps(
            [
                {"event_type": "best_bid_ask", "asset_id": "YES1"},
                {"event_type": "last_trade_price", "asset_id": "YES1", "price": "0.44"},
            ]
        )
    )

    assert len(single) == 1
    assert len(batch) == 2


def test_market_websocket_client_updates_cache_from_stream():
    class _FakeSocket:
        def __init__(self):
            self.sent: list[str] = []
            self._messages = iter(
                [
                    json.dumps({"event_type": "best_bid_ask", "asset_id": "YES1", "best_bid": "0.41", "best_ask": "0.43"}),
                    json.dumps({"event_type": "last_trade_price", "asset_id": "YES1", "price": "0.42"}),
                ]
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def send(self, payload: str):
            self.sent.append(payload)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._messages)
            except StopIteration:
                raise StopAsyncIteration

    fake_socket = _FakeSocket()

    async def _connector(url: str):
        assert url.endswith("/ws/market")
        return fake_socket

    async def _run():
        seen: list[tuple[str, dict[str, object]]] = []
        client = MarketWebSocketClient(asset_ids=["YES1"], connector=_connector)
        snapshots = await client.run_once(max_messages=2, event_handler=lambda event, snapshot: seen.append((event["event_type"], snapshot)))
        assert len(fake_socket.sent) == 1
        assert len(snapshots) == 2
        assert seen[0][0] == "best_bid_ask"
        assert seen[0][1]["token_id"] == "YES1"
        assert client.cache.get("YES1") is not None
        assert client.cache.get("YES1").last_trade_price == 0.42

    asyncio.run(_run())


def test_user_websocket_client_updates_order_manager(monkeypatch, tmp_path):
    from stonks_cli.polymarket import lifecycle

    monkeypatch.setattr(lifecycle, "default_state_dir", lambda: tmp_path)

    class _FakeSocket:
        def __init__(self):
            self.sent: list[str] = []
            self._messages = iter(
                [
                    json.dumps(
                        {
                            "event_type": "order",
                            "id": "order-1",
                            "asset_id": "YES1",
                            "market": "1",
                            "side": "BUY",
                            "price": "0.58",
                            "original_size": "12",
                            "size_matched": "3",
                            "type": "UPDATE",
                            "timestamp": "2026-04-24T00:00:05Z",
                        }
                    )
                ]
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def send(self, payload: str):
            self.sent.append(payload)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._messages)
            except StopIteration:
                raise StopAsyncIteration

    fake_socket = _FakeSocket()

    async def _connector(url: str):
        assert url.endswith("/ws/user")
        return fake_socket

    async def _run():
        cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=False))
        manager = LiveOrderManager(cfg)
        seen: list[dict[str, object]] = []
        manager.register_submitted(
            "order-1",
            build_live_order_request(
                cfg,
                ExecutionOrder(
                    token_id="YES1",
                    market_id="1",
                    slug="btc-higher",
                    outcome="YES",
                    side="BUY",
                    price=0.58,
                    shares=12,
                ),
                LiveMarketSnapshot(token_id="YES1", best_bid=0.57, best_ask=0.60, tick_size=0.01),
            ),
            now="2026-04-24T00:00:00Z",
        )

        client = UserWebSocketClient(
            auth={"apiKey": "k", "secret": "s", "passphrase": "p"},
            market_ids=["1"],
            connector=_connector,
        )
        updates = await client.run_once(
            order_manager=manager,
            max_messages=1,
            event_handler=lambda event, record: seen.append({"event": event, "record": record}),
        )
        assert len(fake_socket.sent) == 1
        assert len(updates) == 1
        assert seen[0]["record"]["order_id"] == "order-1"
        assert manager.records()[0].filled_shares == 3
        assert manager.records()[0].remaining_shares == 9

    asyncio.run(_run())
