from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from stonks_cli.polymarket.lifecycle import LiveOrderManager
from stonks_cli.polymarket.stream import MarketStateCache

MARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
USER_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/user"


def build_market_subscription(asset_ids: list[str], *, channels: list[str] | None = None) -> dict[str, object]:
    assets = [str(asset_id).strip() for asset_id in asset_ids if str(asset_id).strip()]
    if not assets:
        raise ValueError("asset_ids must contain at least one token id")
    return {
        "type": "market",
        "assets_ids": assets,
        "channels": channels or ["market", "best_bid_ask", "price_change", "tick_size_change"],
    }


def build_user_subscription(
    *,
    auth: dict[str, str],
    market_ids: list[str] | None = None,
    asset_ids: list[str] | None = None,
) -> dict[str, object]:
    if not auth:
        raise ValueError("auth is required for user websocket subscription")
    payload: dict[str, object] = {"type": "user", "auth": auth}
    if market_ids:
        payload["markets"] = [str(market_id).strip() for market_id in market_ids if str(market_id).strip()]
    if asset_ids:
        payload["assets_ids"] = [str(asset_id).strip() for asset_id in asset_ids if str(asset_id).strip()]
    return payload


def parse_ws_message(raw: str | bytes | dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload: object
    if isinstance(raw, bytes):
        payload = json.loads(raw.decode("utf-8"))
    elif isinstance(raw, str):
        payload = json.loads(raw)
    else:
        payload = raw
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


class MarketWebSocketClient:
    def __init__(
        self,
        *,
        asset_ids: list[str],
        channels: list[str] | None = None,
        url: str = MARKET_WS_URL,
        cache: MarketStateCache | None = None,
        connector: Callable[[str], Awaitable[object]] | None = None,
    ):
        self._subscription = build_market_subscription(asset_ids, channels=channels)
        self._url = url
        self._cache = cache or MarketStateCache()
        self._connector = connector or _connect_ws

    @property
    def cache(self) -> MarketStateCache:
        return self._cache

    async def run_once(self, *, max_messages: int | None = None) -> list[dict[str, Any]]:
        snapshots: list[dict[str, Any]] = []
        ws = await self._connector(self._url)
        async with ws:
            await ws.send(json.dumps(self._subscription))
            count = 0
            async for raw in ws:
                for event in parse_ws_message(raw):
                    try:
                        snapshot = self._cache.apply(event)
                    except ValueError:
                        continue
                    snapshots.append(
                        {
                            "token_id": snapshot.token_id,
                            "best_bid": snapshot.best_bid,
                            "best_ask": snapshot.best_ask,
                            "midpoint": snapshot.midpoint,
                            "last_trade_price": snapshot.last_trade_price,
                            "tick_size": snapshot.tick_size,
                            "resolved": snapshot.resolved,
                            "last_event_type": snapshot.last_event_type,
                            "last_event_at": snapshot.last_event_at,
                        }
                    )
                count += 1
                if max_messages is not None and count >= max_messages:
                    break
        return snapshots


class UserWebSocketClient:
    def __init__(
        self,
        *,
        auth: dict[str, str],
        market_ids: list[str] | None = None,
        asset_ids: list[str] | None = None,
        url: str = USER_WS_URL,
        connector: Callable[[str], Awaitable[object]] | None = None,
    ):
        self._subscription = build_user_subscription(auth=auth, market_ids=market_ids, asset_ids=asset_ids)
        self._url = url
        self._connector = connector or _connect_ws

    async def run_once(
        self,
        *,
        order_manager: LiveOrderManager,
        max_messages: int | None = None,
    ) -> list[dict[str, Any]]:
        updates: list[dict[str, Any]] = []
        ws = await self._connector(self._url)
        async with ws:
            await ws.send(json.dumps(self._subscription))
            count = 0
            async for raw in ws:
                for event in parse_ws_message(raw):
                    record = order_manager.apply_user_event(event)
                    updates.append({"event": event, "record": None if record is None else asdict_record(record)})
                count += 1
                if max_messages is not None and count >= max_messages:
                    break
        return updates


def asdict_record(record) -> dict[str, Any]:
    return {
        "order_id": record.order_id,
        "token_id": record.token_id,
        "market_id": record.market_id,
        "slug": record.slug,
        "outcome": record.outcome,
        "side": record.side,
        "price": record.price,
        "shares": record.shares,
        "status": record.status,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "remaining_shares": record.remaining_shares,
        "filled_shares": record.filled_shares,
        "cancel_reason": record.cancel_reason,
        "reason": record.reason,
    }


async def _connect_ws(url: str):
    try:
        from websockets.asyncio.client import connect
    except Exception:
        try:
            from websockets.client import connect
        except Exception as e:
            raise ImportError("websocket streaming requires optional dependency `websockets`") from e
    return connect(url)
