from __future__ import annotations

import json
import math
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from stonks_cli.config import AppConfig
from stonks_cli.logging_utils import log_suppressed_exception
from stonks_cli.paths import default_state_dir
from stonks_cli.polymarket.client import _as_float, utc_now_iso
from stonks_cli.polymarket.models import LiveMarketSnapshot, LiveOrderAction, LiveOrderRecord, LiveOrderRequest

if TYPE_CHECKING:
    from stonks_cli.polymarket.execution import ExecutionOrder


def live_orders_path() -> Path:
    return default_state_dir() / "polymarket_live_orders.json"


def _parse_iso(ts: str) -> Any:
    from datetime import datetime

    value = (ts or "").strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def load_live_orders() -> list[LiveOrderRecord]:
    path = live_orders_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log_suppressed_exception(context="polymarket.lifecycle.load_live_orders", error=e, path=path)
        return []
    if not isinstance(payload, list):
        return []
    out: list[LiveOrderRecord] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            out.append(LiveOrderRecord(**item))
        except Exception as e:
            log_suppressed_exception(context="polymarket.lifecycle.parse_live_order", error=e, item=item)
    return out


def save_live_orders(records: list[LiveOrderRecord]) -> None:
    path = live_orders_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([asdict(record) for record in records], ensure_ascii=False, sort_keys=True), encoding="utf-8")
    except Exception as e:
        log_suppressed_exception(context="polymarket.lifecycle.save_live_orders", error=e, path=path)


def normalize_price_to_tick(price: float, *, tick_size: float, side: str) -> float:
    if tick_size <= 0:
        raise ValueError("tick_size must be positive")
    if price <= 0 or price >= 1:
        raise ValueError("price must be between 0 and 1")
    direction = side.upper()
    epsilon = tick_size * 1e-6
    if direction == "BUY":
        snapped = math.floor((price + epsilon) / tick_size) * tick_size
    elif direction == "SELL":
        snapped = math.ceil((price - epsilon) / tick_size) * tick_size
    else:
        raise ValueError(f"unsupported side: {side}")
    return round(min(max(snapped, tick_size), 1.0 - tick_size), 8)


def is_marketable(side: str, price: float, snapshot: LiveMarketSnapshot) -> bool:
    direction = side.upper()
    if direction == "BUY":
        return snapshot.best_ask is not None and price >= snapshot.best_ask
    if direction == "SELL":
        return snapshot.best_bid is not None and price <= snapshot.best_bid
    raise ValueError(f"unsupported side: {side}")


def build_live_order_request(cfg: AppConfig, order: ExecutionOrder, snapshot: LiveMarketSnapshot) -> LiveOrderRequest:
    if snapshot.token_id != order.token_id:
        raise ValueError("snapshot token does not match execution order token")
    if snapshot.resolved:
        raise ValueError("market is already resolved")
    tick_size = snapshot.tick_size or 0.01
    price = normalize_price_to_tick(order.price, tick_size=tick_size, side=order.side)
    if cfg.polymarket.live_post_only and is_marketable(order.side, price, snapshot):
        raise ValueError("post-only live order would cross the spread")
    if snapshot.min_order_size is not None and order.shares < snapshot.min_order_size:
        raise ValueError("order size is below venue minimum")
    return LiveOrderRequest(
        token_id=order.token_id,
        market_id=order.market_id,
        slug=order.slug,
        outcome=order.outcome,
        side=order.side.upper(),
        price=price,
        shares=round(order.shares, 8),
        post_only=cfg.polymarket.live_post_only,
        tick_size=tick_size,
        reason=order.reason,
    )


def _event_order_id(event: dict[str, Any]) -> str | None:
    value = event.get("order_id", event.get("orderId", event.get("id")))
    if value in (None, ""):
        return None
    return str(value)


def _event_status(event: dict[str, Any]) -> str | None:
    for key in ("status", "state", "event_type", "eventType", "type"):
        value = event.get(key)
        if value not in (None, ""):
            return str(value).upper()
    return None


class LiveOrderManager:
    def __init__(self, cfg: AppConfig):
        self._cfg = cfg
        self._records = {record.order_id: record for record in load_live_orders()}

    def records(self) -> list[LiveOrderRecord]:
        return sorted(self._records.values(), key=lambda record: record.created_at)

    def register_submitted(self, order_id: str, request: LiveOrderRequest, *, now: str | None = None) -> LiveOrderRecord:
        ts = now or utc_now_iso()
        record = LiveOrderRecord(
            order_id=order_id,
            token_id=request.token_id,
            market_id=request.market_id,
            slug=request.slug,
            outcome=request.outcome,
            side=request.side,
            price=request.price,
            shares=request.shares,
            status="OPEN",
            created_at=ts,
            updated_at=ts,
            remaining_shares=request.shares,
            filled_shares=0.0,
            reason=request.reason,
        )
        self._records[record.order_id] = record
        save_live_orders(self.records())
        return record

    def apply_user_event(self, event: dict[str, Any], *, now: str | None = None) -> LiveOrderRecord | None:
        event_type = str(event.get("event_type") or "").lower()
        if event_type == "trade":
            updated = self._apply_trade_event(event, now=now)
            if updated is not None:
                save_live_orders(self.records())
            return updated
        updated = self._apply_order_event(event, now=now)
        if updated is not None:
            save_live_orders(self.records())
        return updated

    def _apply_order_event(self, event: dict[str, Any], *, now: str | None = None) -> LiveOrderRecord | None:
        order_id = _event_order_id(event)
        if not order_id:
            return None
        record = self._records.get(order_id)
        ts = now or str(event.get("timestamp") or event.get("ts") or utc_now_iso())
        status = _event_status(event) or "OPEN"
        original_size = _as_float(event.get("original_size", event.get("size", event.get("originalSize"))))
        size_matched = _as_float(event.get("size_matched", event.get("filled_size", event.get("sizeMatched"))))
        remaining_shares = _as_float(event.get("remaining_size", event.get("remainingSize")))
        if original_size is not None and size_matched is not None:
            remaining_shares = max(0.0, round(original_size - size_matched, 8))
        if record is None:
            shares = original_size if original_size is not None else _as_float(event.get("size")) or 0.0
            record = LiveOrderRecord(
                order_id=order_id,
                token_id=str(event.get("asset_id") or event.get("assetId") or ""),
                market_id=str(event.get("market") or ""),
                slug=None,
                outcome=event.get("outcome"),
                side=str(event.get("side") or ""),
                price=_as_float(event.get("price")) or 0.0,
                shares=shares,
                status=status,
                created_at=ts,
                updated_at=ts,
                remaining_shares=shares if remaining_shares is None else remaining_shares,
                filled_shares=0.0 if size_matched is None else size_matched,
            )
        else:
            record = replace(
                record,
                status=status,
                updated_at=ts,
                filled_shares=record.filled_shares if size_matched is None else size_matched,
                remaining_shares=record.remaining_shares if remaining_shares is None else remaining_shares,
            )
        self._records[order_id] = record
        return record

    def _apply_trade_event(self, event: dict[str, Any], *, now: str | None = None) -> LiveOrderRecord | None:
        ts = now or str(event.get("timestamp") or event.get("last_update") or utc_now_iso())
        status = str(event.get("status") or "MATCHED")
        for maker_order in event.get("maker_orders") or []:
            if not isinstance(maker_order, dict):
                continue
            order_id = str(maker_order.get("order_id") or "").strip()
            if not order_id or order_id not in self._records:
                continue
            record = self._records[order_id]
            matched = _as_float(maker_order.get("matched_amount")) or 0.0
            filled = min(record.shares, round(record.filled_shares + matched, 8))
            remaining = max(0.0, round(record.shares - filled, 8))
            updated = replace(
                record,
                status=status,
                updated_at=ts,
                filled_shares=filled,
                remaining_shares=remaining,
            )
            self._records[order_id] = updated
            return updated

        taker_order_id = str(event.get("taker_order_id") or "").strip()
        if taker_order_id and taker_order_id in self._records:
            record = self._records[taker_order_id]
            size = _as_float(event.get("size")) or record.shares
            filled = min(record.shares, size)
            updated = replace(
                record,
                status=status,
                updated_at=ts,
                filled_shares=filled,
                remaining_shares=max(0.0, round(record.shares - filled, 8)),
            )
            self._records[taker_order_id] = updated
            return updated
        return None

    def sync_open_orders(self, open_orders: list[dict[str, Any]], *, now: str | None = None) -> list[LiveOrderRecord]:
        updated: list[LiveOrderRecord] = []
        seen: set[str] = set()
        for order in open_orders:
            if not isinstance(order, dict):
                continue
            record = self._apply_order_event(order, now=now)
            if record is not None:
                seen.add(record.order_id)
                updated.append(record)
        for order_id, record in list(self._records.items()):
            if record.status in {"OPEN", "PLACEMENT", "UPDATE", "LIVE", "PARTIAL"} and order_id not in seen:
                self._records[order_id] = replace(
                    record,
                    status="STALE_LOCAL",
                    updated_at=now or utc_now_iso(),
                )
        save_live_orders(self.records())
        return updated

    def stale_cancels(self, *, now: str | None = None) -> list[LiveOrderAction]:
        ts = _parse_iso(now or utc_now_iso())
        out: list[LiveOrderAction] = []
        open_statuses = {"OPEN", "LIVE", "PLACED", "PARTIAL"}
        for record in self._records.values():
            if record.status not in open_statuses:
                continue
            age = (ts - _parse_iso(record.created_at)).total_seconds()
            if age < self._cfg.polymarket.live_order_max_age_seconds:
                continue
            out.append(
                LiveOrderAction(
                    action="CANCEL",
                    order_id=record.order_id,
                    token_id=record.token_id,
                    reason="stale_open_order",
                )
            )
        return out

    def mark_cancelled(self, order_id: str, *, reason: str, now: str | None = None) -> LiveOrderRecord | None:
        record = self._records.get(order_id)
        if record is None:
            return None
        updated = replace(
            record,
            status="CANCELLED",
            cancel_reason=reason,
            updated_at=now or utc_now_iso(),
        )
        self._records[order_id] = updated
        save_live_orders(self.records())
        return updated
