from __future__ import annotations

import asyncio
import json
import platform
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stonks_cli.carry.carry_storage import CarryStorage
from stonks_cli.research.hyperliquid import HYPERLIQUID_WS_URL
from stonks_cli.research.models import CarryQuote, FundingSnapshot, NormalizedTrade, TradeSide, Venue

DEFAULT_CAPTURE_FIXTURE = Path("tests/fixtures/research/hyperliquid-ws.jsonl")
DEFAULT_LIVE_CAPTURE_COINS = ("BTC", "ETH", "SOL")
DEFAULT_LIVE_CAPTURE_SECONDS = 7 * 24 * 60 * 60


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
    decoded_events: int = 0
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


def build_all_mids_subscription(*, dex: str | None = None) -> dict[str, Any]:
    subscription: dict[str, Any] = {"type": "allMids"}
    if dex:
        subscription["dex"] = dex
    return {"method": "subscribe", "subscription": subscription}


def build_user_fills_subscription(*, user: str, aggregate_by_time: bool | None = None) -> dict[str, Any]:
    subscription: dict[str, Any] = {"type": "userFills", "user": user.lower()}
    if aggregate_by_time is not None:
        subscription["aggregateByTime"] = aggregate_by_time
    return {"method": "subscribe", "subscription": subscription}


def build_user_fundings_subscription(*, user: str) -> dict[str, Any]:
    return {"method": "subscribe", "subscription": {"type": "userFundings", "user": user.lower()}}


def build_active_asset_ctx_subscription(*, coin: str) -> dict[str, Any]:
    return {"method": "subscribe", "subscription": {"type": "activeAssetCtx", "coin": coin}}


def build_unsubscribe(subscription: dict[str, Any]) -> dict[str, Any]:
    if subscription.get("method") == "subscribe":
        subscription = dict(subscription["subscription"])
    return {"method": "unsubscribe", "subscription": subscription}


def build_live_capture_subscriptions(
    *,
    coins: list[str] | tuple[str, ...] = DEFAULT_LIVE_CAPTURE_COINS,
    user_fill_wallets: list[str] | tuple[str, ...] = (),
    user_funding_wallets: list[str] | tuple[str, ...] = (),
    include_all_mids: bool = True,
    all_mids_dex: str | None = None,
) -> list[dict[str, Any]]:
    subscriptions: list[dict[str, Any]] = []
    for coin in coins:
        normalized = coin.strip()
        if normalized:
            subscriptions.append(build_trades_subscription(coin=normalized))
    if include_all_mids:
        subscriptions.append(build_all_mids_subscription(dex=all_mids_dex))
    for wallet in user_fill_wallets:
        normalized = wallet.strip().lower()
        if normalized:
            subscriptions.append(build_user_fills_subscription(user=normalized, aggregate_by_time=False))
    for wallet in user_funding_wallets:
        normalized = wallet.strip().lower()
        if normalized:
            subscriptions.append(build_user_fundings_subscription(user=normalized))
    if not subscriptions:
        raise HyperliquidIngestionError("at least one Hyperliquid websocket subscription is required")
    return subscriptions


def build_carry_capture_subscriptions(
    *,
    assets: list[str] | tuple[str, ...] = ("BTC", "ETH"),
    include_all_mids: bool = True,
    all_mids_dex: str | None = None,
) -> list[dict[str, Any]]:
    subscriptions = [build_active_asset_ctx_subscription(coin=asset.strip().upper()) for asset in assets if asset.strip()]
    if include_all_mids:
        subscriptions.insert(0, build_all_mids_subscription(dex=all_mids_dex))
    if not subscriptions:
        raise HyperliquidIngestionError("at least one Carry websocket subscription is required")
    return subscriptions


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


def decode_carry_ws_message(
    message: str | dict[str, Any],
    *,
    assets: tuple[str, ...] = ("BTC", "ETH"),
    received_at_utc: str | None = None,
) -> list[CarryQuote | FundingSnapshot]:
    payload = json.loads(message) if isinstance(message, str) else message
    if not isinstance(payload, dict):
        raise HyperliquidIngestionError("websocket message must be a JSON object")
    timestamp = received_at_utc or _iso(_now())
    channel = str(payload.get("channel") or "")
    data = payload.get("data")
    if channel == "allMids":
        mids = data.get("mids") if isinstance(data, dict) and isinstance(data.get("mids"), dict) else {}
        return _carry_quotes_from_all_mids(mids, assets=assets, timestamp=timestamp)
    if channel in {"activeAssetCtx", "activeSpotAssetCtx"} and isinstance(data, dict):
        return _carry_snapshots_from_asset_ctx(data, assets=assets, timestamp=timestamp)
    return []


def record_carry_ws_message(
    message: str | dict[str, Any],
    *,
    storage: CarryStorage,
    assets: tuple[str, ...] = ("BTC", "ETH"),
    received_at_utc: str | None = None,
) -> int:
    snapshots = decode_carry_ws_message(message, assets=assets, received_at_utc=received_at_utc)
    for snapshot in snapshots:
        if isinstance(snapshot, CarryQuote):
            storage.write_quote(snapshot)
        elif isinstance(snapshot, FundingSnapshot):
            storage.write_funding(snapshot)
    return len(snapshots)


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
            self.health.decoded_events += _decoded_event_count(payload, trades)
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
        raw_handler: Callable[[str], Awaitable[None]] | None = None,
        health_handler: Callable[[IngestionHealth], Awaitable[None]] | None = None,
        stop_after_messages: int | None = None,
        stop_after_seconds: float | None = None,
        max_reconnects: int | None = None,
        heartbeat_seconds: float = 30.0,
    ) -> IngestionHealth:
        try:
            import websockets
        except ImportError as e:
            raise HyperliquidIngestionError("Hyperliquid websocket ingestion requires websockets>=12") from e

        attempt = 0
        seen_messages = 0
        loop = asyncio.get_running_loop()
        started = loop.time()
        deadline = started + stop_after_seconds if stop_after_seconds is not None else None
        while max_reconnects is None or attempt <= max_reconnects:
            if deadline is not None and loop.time() >= deadline:
                return self.monitor.health
            if attempt:
                await asyncio.sleep(self.backoff.delay(attempt))
            try:
                async with websockets.connect(self.ws_url) as websocket:
                    for subscription in self.subscriptions:
                        await websocket.send(json.dumps(subscription))
                    attempt = 0
                    while True:
                        if deadline is not None and loop.time() >= deadline:
                            return self.monitor.health
                        timeout = heartbeat_seconds
                        if deadline is not None:
                            timeout = max(0.1, min(timeout, deadline - loop.time()))
                        try:
                            raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                        except TimeoutError:
                            await websocket.send(json.dumps({"method": "ping"}))
                            continue
                        seen_messages += 1
                        raw_text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                        if raw_handler is not None:
                            await raw_handler(raw_text)
                        for trade in self.monitor.record_message(raw_text):
                            await handler(trade)
                        if health_handler is not None:
                            await health_handler(self.monitor.health)
                        if stop_after_messages is not None and seen_messages >= stop_after_messages:
                            return self.monitor.health
            except Exception as e:
                attempt += 1
                self.monitor.record_reconnect(str(e))
                if max_reconnects is not None and attempt > max_reconnects:
                    self.monitor.health.last_error = f"max_reconnects_exceeded: {e}"
                    break
        return self.monitor.health


async def capture_hyperliquid_to_files(
    *,
    subscriptions: list[dict[str, Any]],
    raw_out_path: Path | str,
    trades_out_path: Path | str,
    health_out_path: Path | str,
    duration_seconds: float = DEFAULT_LIVE_CAPTURE_SECONDS,
    ws_url: str = HYPERLIQUID_WS_URL,
    heartbeat_seconds: float = 30.0,
    health_interval_seconds: float = 60.0,
    max_reconnects: int | None = None,
    stop_after_messages: int | None = None,
    carry_storage: CarryStorage | None = None,
    progress_handler: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    raw_path = Path(raw_out_path)
    trades_path = Path(trades_out_path)
    health_path = Path(health_out_path)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    trades_path.parent.mkdir(parents=True, exist_ok=True)
    health_path.parent.mkdir(parents=True, exist_ok=True)

    monitor = IngestionMonitor()
    ingestor = HyperliquidWebsocketIngestor(subscriptions=subscriptions, ws_url=ws_url, monitor=monitor)
    started_at = _iso(_now())
    started_monotonic = time.monotonic()
    last_health_write = 0.0

    async def write_health(status: str) -> dict[str, Any]:
        payload = _capture_health_payload(
            status=status,
            health=monitor.health,
            started_at_utc=started_at,
            raw_out_path=raw_path,
            trades_out_path=trades_path,
            health_out_path=health_path,
            subscriptions=subscriptions,
            ws_url=ws_url,
            duration_seconds=time.monotonic() - started_monotonic,
        )
        health_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if progress_handler is not None:
            await progress_handler(payload)
        return payload

    async def maybe_write_health(health: IngestionHealth) -> None:
        nonlocal last_health_write
        _ = health
        now = time.monotonic()
        if now - last_health_write >= health_interval_seconds:
            last_health_write = now
            await write_health("running")

    async def record_raw(raw: str) -> None:
        received_at_utc = _iso(_now())
        row = {"received_at_utc": received_at_utc, "raw": _json_or_text(raw)}
        raw_handle.write(json.dumps(row, sort_keys=True) + "\n")
        if carry_storage is not None:
            record_carry_ws_message(raw, storage=carry_storage, received_at_utc=received_at_utc)

    async def record_trade(trade: NormalizedTrade) -> None:
        trades_handle.write(json.dumps(trade.to_dict(), sort_keys=True) + "\n")

    with raw_path.open("a", encoding="utf-8", buffering=1) as raw_handle, trades_path.open(
        "a", encoding="utf-8", buffering=1
    ) as trades_handle:
        await write_health("running")
        await ingestor.run(
            record_trade,
            raw_handler=record_raw,
            health_handler=maybe_write_health,
            stop_after_messages=stop_after_messages,
            stop_after_seconds=duration_seconds,
            max_reconnects=max_reconnects,
            heartbeat_seconds=heartbeat_seconds,
        )
        return await write_health(_capture_final_status(monitor.health))


def runtime_host_metadata() -> dict[str, Any]:
    return {
        "os": platform.system(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }


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


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decoded_event_count(payload: dict[str, Any], trades: list[NormalizedTrade]) -> int:
    channel = str(payload.get("channel") or "")
    if channel in {"subscriptionResponse", "pong"}:
        return 0
    if trades:
        return len(trades)
    known_channels = {
        "allMids",
        "activeAssetCtx",
        "activeSpotAssetCtx",
        "bbo",
        "candle",
        "l2Book",
        "orderUpdates",
        "trades",
        "userEvents",
        "userFills",
        "userFundings",
        "userNonFundingLedgerUpdates",
    }
    return 1 if channel in known_channels else 0


def _carry_quotes_from_all_mids(mids: dict[str, Any], *, assets: tuple[str, ...], timestamp: str) -> list[CarryQuote]:
    quotes = []
    for asset in assets:
        normalized = asset.upper()
        spot_mid = _mid_for(mids, f"{normalized}/USDC", f"U{normalized}/USDC")
        perp_mid = _mid_for(mids, normalized)
        if spot_mid is None and perp_mid is None:
            continue
        missing = []
        if spot_mid is None:
            missing.append("spot_mid")
        if perp_mid is None:
            missing.append("perp_mid")
        quotes.append(
            CarryQuote(
                venue=Venue.HYPERLIQUID,
                asset=normalized,
                spot_mid=spot_mid,
                perp_mid=perp_mid,
                oracle_mid=None,
                mark_mid=None,
                timestamp=timestamp,
                source_health="ws_allMids" if not missing else f"ws_allMids_missing:{','.join(missing)}",
            )
        )
    return quotes


def _carry_snapshots_from_asset_ctx(data: dict[str, Any], *, assets: tuple[str, ...], timestamp: str) -> list[CarryQuote | FundingSnapshot]:
    coin = str(data.get("coin") or "").upper()
    ctx = data.get("ctx") if isinstance(data.get("ctx"), dict) else data
    if coin not in {asset.upper() for asset in assets}:
        return []
    mark_mid = _maybe_float(ctx.get("markPx"))
    oracle_mid = _maybe_float(ctx.get("oraclePx"))
    funding_rate = _maybe_float(ctx.get("funding"))
    snapshots: list[CarryQuote | FundingSnapshot] = [
        CarryQuote(
            venue=Venue.HYPERLIQUID,
            asset=coin,
            spot_mid=None,
            perp_mid=None,
            oracle_mid=oracle_mid,
            mark_mid=mark_mid,
            timestamp=timestamp,
            source_health="ws_activeAssetCtx",
        )
    ]
    if funding_rate is not None:
        snapshots.append(
            FundingSnapshot(
                asset=coin,
                venue=Venue.HYPERLIQUID,
                hourly_rate=funding_rate,
                annualized_rate=funding_rate * 24 * 365,
                next_funding_time=None,
                premium_index=_maybe_float(ctx.get("premium")),
                timestamp=timestamp,
            )
        )
    return snapshots


def _mid_for(mids: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in mids:
            return _maybe_float(mids[key])
    return None


def _maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(str(value))


def _capture_final_status(health: IngestionHealth) -> str:
    if str(health.last_error or "").startswith("max_reconnects_exceeded:"):
        return "max_reconnects_exceeded"
    if health.malformed_messages or health.dropped_messages:
        return "needs_attention"
    return "clean_capture"


def _capture_health_payload(
    *,
    status: str,
    health: IngestionHealth,
    started_at_utc: str,
    raw_out_path: Path,
    trades_out_path: Path,
    health_out_path: Path,
    subscriptions: list[dict[str, Any]],
    ws_url: str,
    duration_seconds: float,
) -> dict[str, Any]:
    return {
        "source": "live_capture",
        "started_at_utc": started_at_utc,
        "updated_at_utc": _iso(_now()),
        "duration_seconds": round(duration_seconds, 3),
        "ws_url": ws_url,
        "subscriptions": subscriptions,
        "raw_out_path": str(raw_out_path),
        "capture_out_path": str(trades_out_path),
        "health_out_path": str(health_out_path),
        "runtime": runtime_host_metadata(),
        "health": health.to_dict(),
        "decoded_trade_count": health.decoded_trades,
        "decoded_event_count": health.decoded_events,
        "final_status": status,
    }


def _json_or_text(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return raw
