from __future__ import annotations

from dataclasses import replace
from typing import Any

from stonks_cli.polymarket.client import _as_float, _pick, utc_now_iso
from stonks_cli.polymarket.models import BookLevel, LiveMarketSnapshot, OrderBook


def _event_token_id(event: dict[str, Any]) -> str | None:
    token_id = _pick(event, "asset_id", "assetId", "token_id", "tokenId")
    if token_id in (None, ""):
        return None
    return str(token_id)


def _event_type(event: dict[str, Any]) -> str:
    return str(_pick(event, "event_type", "eventType", "type") or "unknown")


def _best(levels: list[BookLevel], *, side: str) -> float | None:
    if not levels:
        return None
    prices = [level.price for level in levels]
    return max(prices) if side == "bid" else min(prices)


def _midpoint(best_bid: float | None, best_ask: float | None, fallback: float | None = None) -> float | None:
    if best_bid is not None and best_ask is not None:
        return round((best_bid + best_ask) / 2.0, 6)
    if best_bid is not None:
        return best_bid
    if best_ask is not None:
        return best_ask
    return fallback


def _parse_levels(raw_levels: Any) -> list[BookLevel]:
    if not isinstance(raw_levels, list):
        return []
    out: list[BookLevel] = []
    for item in raw_levels:
        if isinstance(item, dict):
            price = _as_float(_pick(item, "price"))
            size = _as_float(_pick(item, "size", "amount"))
        elif isinstance(item, list) and len(item) >= 2:
            price = _as_float(item[0])
            size = _as_float(item[1])
        else:
            continue
        if price is None or size is None:
            continue
        out.append(BookLevel(price=price, size=size))
    return out


def snapshot_from_book(book: OrderBook, *, tick_size: float | None = None) -> LiveMarketSnapshot:
    return LiveMarketSnapshot(
        token_id=book.token_id,
        best_bid=book.best_bid,
        best_ask=book.best_ask,
        midpoint=book.midpoint,
        tick_size=tick_size or _as_float(book.raw.get("tick_size")) or 0.01,
        bids=book.bids,
        asks=book.asks,
        last_event_type="book",
        last_event_at=utc_now_iso(),
    )


def reduce_market_event(snapshot: LiveMarketSnapshot | None, event: dict[str, Any]) -> LiveMarketSnapshot:
    token_id = _event_token_id(event)
    if not token_id:
        raise ValueError("market event is missing token identifier")
    current = snapshot or LiveMarketSnapshot(token_id=token_id)
    event_type = _event_type(event)
    last_event_at = str(_pick(event, "timestamp", "ts", "time")) if _pick(event, "timestamp", "ts", "time") else utc_now_iso()

    if event_type == "book":
        bids = _parse_levels(event.get("bids"))
        asks = _parse_levels(event.get("asks"))
        best_bid = _best(bids, side="bid")
        best_ask = _best(asks, side="ask")
        return replace(
            current,
            bids=bids,
            asks=asks,
            best_bid=best_bid,
            best_ask=best_ask,
            midpoint=_midpoint(best_bid, best_ask, current.midpoint),
            tick_size=_as_float(_pick(event, "tick_size", "tickSize")) or current.tick_size,
            min_order_size=_as_float(_pick(event, "min_order_size", "minOrderSize")) or current.min_order_size,
            last_event_type=event_type,
            last_event_at=last_event_at,
        )

    if event_type == "best_bid_ask":
        best_bid = _as_float(_pick(event, "best_bid", "bestBid"))
        best_ask = _as_float(_pick(event, "best_ask", "bestAsk"))
        return replace(
            current,
            best_bid=best_bid if best_bid is not None else current.best_bid,
            best_ask=best_ask if best_ask is not None else current.best_ask,
            midpoint=_midpoint(best_bid if best_bid is not None else current.best_bid, best_ask if best_ask is not None else current.best_ask, current.midpoint),
            last_event_type=event_type,
            last_event_at=last_event_at,
        )

    if event_type in {"price_change", "last_trade_price"}:
        last_trade_price = _as_float(_pick(event, "price", "last_trade_price", "lastTradePrice"))
        return replace(
            current,
            last_trade_price=last_trade_price if last_trade_price is not None else current.last_trade_price,
            last_event_type=event_type,
            last_event_at=last_event_at,
        )

    if event_type == "tick_size_change":
        tick_size = _as_float(_pick(event, "tick_size", "tickSize"))
        if tick_size is None or tick_size <= 0:
            return replace(current, last_event_type=event_type, last_event_at=last_event_at)
        return replace(current, tick_size=tick_size, last_event_type=event_type, last_event_at=last_event_at)

    if event_type == "market_resolved":
        return replace(current, resolved=True, last_event_type=event_type, last_event_at=last_event_at)

    return replace(current, last_event_type=event_type, last_event_at=last_event_at)


class MarketStateCache:
    def __init__(self) -> None:
        self._snapshots: dict[str, LiveMarketSnapshot] = {}

    def apply(self, event: dict[str, Any]) -> LiveMarketSnapshot:
        token_id = _event_token_id(event)
        if not token_id:
            raise ValueError("market event is missing token identifier")
        snapshot = reduce_market_event(self._snapshots.get(token_id), event)
        self._snapshots[token_id] = snapshot
        return snapshot

    def upsert_snapshot(self, snapshot: LiveMarketSnapshot) -> LiveMarketSnapshot:
        self._snapshots[snapshot.token_id] = snapshot
        return snapshot

    def get(self, token_id: str) -> LiveMarketSnapshot | None:
        return self._snapshots.get(token_id)

    def as_dict(self) -> dict[str, LiveMarketSnapshot]:
        return dict(self._snapshots)
