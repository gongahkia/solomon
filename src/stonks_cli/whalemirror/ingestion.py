from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stonks_cli.whalemirror.hyperliquid import HYPERLIQUID_WS_URL
from stonks_cli.whalemirror.models import NormalizedTrade, TradeSide, Venue

DEFAULT_CAPTURE_FIXTURE = Path("tests/fixtures/whalemirror/hyperliquid-ws.jsonl")


class HyperliquidIngestionError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackoffPolicy:
    base_seconds: float = 1.0
    max_seconds: float = 60.0
    multiplier: float = 2.0

    def delay(self, attempt: int) -> float:
        if attempt <= 0:
            return 0.0
        return min(self.max_seconds, self.base_seconds * (self.multiplier ** (attempt - 1)))


@dataclass
class IngestionHealth:
    messages_received: int = 0
    decoded_trades: int = 0
    malformed_messages: int = 0
    dropped_messages: int = 0
    reconnects: int = 0
    last_event_time_ms: int | None = None
    last_error: str | None = None
    last_sequence_by_channel: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_trades_subscription(*, coin: str) -> dict[str, Any]:
    return {"method": "subscribe", "subscription": {"type": "trades", "coin": coin}}


def build_user_fills_subscription(*, user: str, aggregate_by_time: bool | None = None) -> dict[str, Any]:
    subscription: dict[str, Any] = {"type": "userFills", "user": user.lower()}
    if aggregate_by_time is not None:
        subscription["aggregateByTime"] = aggregate_by_time
    return {"method": "subscribe", "subscription": subscription}


def build_user_fundings_subscription(*, user: str) -> dict[str, Any]:
    return {"method": "subscribe", "subscription": {"type": "userFundings", "user": user.lower()}}


def build_unsubscribe(subscription: dict[str, Any]) -> dict[str, Any]:
    if subscription.get("method") == "subscribe":
        subscription = dict(subscription["subscription"])
    return {"method": "unsubscribe", "subscription": subscription}


def decode_ws_message(message: str | dict[str, Any]) -> list[NormalizedTrade]:
    payload = json.loads(message) if isinstance(message, str) else message
    if not isinstance(payload, dict):
        raise HyperliquidIngestionError("websocket message must be a JSON object")

    channel = str(payload.get("channel") or "")
    data = payload.get("data")
    if channel == "subscriptionResponse" or channel == "pong":
        return []
    if channel == "trades":
        rows = data if isinstance(data, list) else []
        return [trade for row in rows for trade in _decode_public_trade(row)]
    if channel == "userFills":
        return _decode_user_fills(data)
    if channel == "userEvents":
        return _decode_user_events(data)
    return []


def replay_capture_fixture(path: Path | str = DEFAULT_CAPTURE_FIXTURE) -> tuple[list[NormalizedTrade], IngestionHealth]:
    monitor = IngestionMonitor()
    trades: list[NormalizedTrade] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        trades.extend(monitor.record_message(line))
    return trades, monitor.health


def write_capture_jsonl(trades: list[NormalizedTrade], path: Path | str) -> None:
    use_path = Path(path)
    use_path.parent.mkdir(parents=True, exist_ok=True)
    with use_path.open("w", encoding="utf-8") as handle:
        for trade in trades:
            handle.write(json.dumps(trade.to_dict(), sort_keys=True) + "\n")


class IngestionMonitor:
    def __init__(self) -> None:
        self.health = IngestionHealth()

    def record_message(self, message: str | dict[str, Any]) -> list[NormalizedTrade]:
        self.health.messages_received += 1
        try:
            payload = json.loads(message) if isinstance(message, str) else message
            if not isinstance(payload, dict):
                raise HyperliquidIngestionError("websocket message must be a JSON object")
            self._record_sequence(payload)
            trades = decode_ws_message(payload)
        except Exception as e:
            self.health.malformed_messages += 1
            self.health.last_error = str(e)
            return []

        self.health.decoded_trades += len(trades)
        event_times = [int(t.raw["time"]) for t in trades if "time" in t.raw]
        if event_times:
            self.health.last_event_time_ms = max(event_times)
        return trades

    def record_reconnect(self, reason: str) -> None:
        self.health.reconnects += 1
        self.health.last_error = reason

    def _record_sequence(self, payload: dict[str, Any]) -> None:
        sequence = payload.get("sequence", payload.get("seq"))
        if sequence is None:
            return
        channel = str(payload.get("channel") or "unknown")
        current = int(sequence)
        previous = self.health.last_sequence_by_channel.get(channel)
        if previous is not None and current > previous + 1:
            self.health.dropped_messages += current - previous - 1
        self.health.last_sequence_by_channel[channel] = current


class HyperliquidWebsocketIngestor:
    def __init__(
        self,
        *,
        subscriptions: list[dict[str, Any]],
        ws_url: str = HYPERLIQUID_WS_URL,
        backoff: BackoffPolicy | None = None,
        monitor: IngestionMonitor | None = None,
    ) -> None:
        self.subscriptions = subscriptions
        self.ws_url = ws_url
        self.backoff = backoff or BackoffPolicy()
        self.monitor = monitor or IngestionMonitor()

    async def run(
        self,
        handler: Callable[[NormalizedTrade], Awaitable[None]],
        *,
        stop_after_messages: int | None = None,
        max_reconnects: int | None = None,
    ) -> IngestionHealth:
        try:
            import websockets
        except ImportError as e:
            raise HyperliquidIngestionError("Hyperliquid websocket ingestion requires websockets>=12") from e

        attempt = 0
        seen_messages = 0
        while max_reconnects is None or attempt <= max_reconnects:
            if attempt:
                await asyncio.sleep(self.backoff.delay(attempt))
            try:
                async with websockets.connect(self.ws_url) as websocket:
                    for subscription in self.subscriptions:
                        await websocket.send(json.dumps(subscription))
                    attempt = 0
                    async for raw in websocket:
                        seen_messages += 1
                        for trade in self.monitor.record_message(str(raw)):
                            await handler(trade)
                        if stop_after_messages is not None and seen_messages >= stop_after_messages:
                            return self.monitor.health
            except Exception as e:
                attempt += 1
                self.monitor.record_reconnect(str(e))
                if max_reconnects is not None and attempt > max_reconnects:
                    break
        return self.monitor.health


def _decode_public_trade(row: Any) -> list[NormalizedTrade]:
    if not isinstance(row, dict):
        raise HyperliquidIngestionError("trade row must be an object")
    coin = str(row["coin"])
    users = row.get("users") or []
    if not isinstance(users, list) or len(users) != 2:
        raise HyperliquidIngestionError("public trade row must include buyer and seller users")
    price = _as_float(row["px"])
    size = _as_float(row["sz"])
    time_ms = int(row["time"])
    tid = str(row["tid"])
    buyer, seller = str(users[0]).lower(), str(users[1]).lower()
    base = {
        "venue": Venue.HYPERLIQUID,
        "market": _market(coin),
        "asset": _asset(coin),
        "price": price,
        "size": size,
        "notional_usd": round(price * size, 8),
        "observed_at": _millis_to_utc(time_ms),
        "raw": dict(row),
    }
    return [
        NormalizedTrade(trade_id=f"{time_ms}:{coin}:{tid}:buy", wallet=buyer, side=TradeSide.BUY, **base),
        NormalizedTrade(trade_id=f"{time_ms}:{coin}:{tid}:sell", wallet=seller, side=TradeSide.SELL, **base),
    ]


def _decode_user_fills(data: Any) -> list[NormalizedTrade]:
    if not isinstance(data, dict):
        raise HyperliquidIngestionError("userFills payload must be an object")
    user = str(data.get("user") or "").lower()
    fills = data.get("fills") or []
    if not user:
        raise HyperliquidIngestionError("userFills payload missing user")
    if not isinstance(fills, list):
        raise HyperliquidIngestionError("userFills fills must be a list")
    return [_decode_fill(fill, user=user) for fill in fills]


def _decode_user_events(data: Any) -> list[NormalizedTrade]:
    if not isinstance(data, dict):
        raise HyperliquidIngestionError("userEvents payload must be an object")
    user = str(data.get("user") or "").lower()
    fills = data.get("fills") or []
    if not fills:
        return []
    if not user:
        user = str(data.get("wallet") or data.get("address") or "").lower()
    if not user:
        raise HyperliquidIngestionError("userEvents fill payload missing user")
    if not isinstance(fills, list):
        raise HyperliquidIngestionError("userEvents fills must be a list")
    return [_decode_fill(fill, user=user) for fill in fills]


def _decode_fill(fill: Any, *, user: str) -> NormalizedTrade:
    if not isinstance(fill, dict):
        raise HyperliquidIngestionError("fill must be an object")
    coin = str(fill["coin"])
    price = _as_float(fill["px"])
    size = _as_float(fill["sz"])
    time_ms = int(fill["time"])
    tid = str(fill["tid"])
    return NormalizedTrade(
        venue=Venue.HYPERLIQUID,
        trade_id=f"{time_ms}:{coin}:{tid}:{user}",
        wallet=user,
        market=_market(coin),
        asset=_asset(coin),
        side=_side(fill),
        price=price,
        size=size,
        notional_usd=round(price * size, 8),
        observed_at=_millis_to_utc(time_ms),
        raw=dict(fill),
    )


def _side(row: dict[str, Any]) -> TradeSide:
    raw = str(row.get("side") or "").strip().lower()
    if raw in {"b", "buy", "bid"}:
        return TradeSide.BUY
    if raw in {"a", "s", "sell", "ask"}:
        return TradeSide.SELL
    direction = str(row.get("dir") or "").lower()
    if "short" in direction or "sell" in direction:
        return TradeSide.SELL
    return TradeSide.BUY


def _market(coin: str) -> str:
    return coin if coin.startswith("@") or "/" in coin else f"{coin}-PERP"


def _asset(coin: str) -> str:
    if coin.startswith("@"):
        return coin
    return coin.split("/", maxsplit=1)[0]


def _millis_to_utc(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat().replace("+00:00", "Z")


def _as_float(value: Any) -> float:
    return float(str(value))
