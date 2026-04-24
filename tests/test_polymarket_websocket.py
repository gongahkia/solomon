from __future__ import annotations

import asyncio
import json

import pytest

from stonks_cli.polymarket.websocket import MarketWebSocketClient, build_market_subscription, parse_ws_message


def test_build_market_subscription_requires_assets():
    with pytest.raises(ValueError):
        build_market_subscription([])


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
        client = MarketWebSocketClient(asset_ids=["YES1"], connector=_connector)
        snapshots = await client.run_once(max_messages=2)
        assert len(fake_socket.sent) == 1
        assert len(snapshots) == 2
        assert client.cache.get("YES1") is not None
        assert client.cache.get("YES1").last_trade_price == 0.42

    asyncio.run(_run())
