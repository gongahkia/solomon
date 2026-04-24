from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stonks_cli.config import AppConfig
from stonks_cli.polymarket.lifecycle import LiveOrderManager
from stonks_cli.polymarket.runtime import run_runtime_loop
from stonks_cli.polymarket.stream import MarketStateCache


def load_event_file(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text[0] == "[":
        payload = json.loads(text)
        return [item for item in payload if isinstance(item, dict)]
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            out.append(payload)
    return out


def replay_market_events(path: Path, *, market_cache: MarketStateCache | None = None) -> dict[str, object]:
    market_cache = market_cache or MarketStateCache()
    applied = 0
    for event in load_event_file(path):
        try:
            market_cache.apply(event)
        except ValueError:
            continue
        applied += 1
    return {
        "applied": applied,
        "snapshots": {
            token_id: {
                "best_bid": snapshot.best_bid,
                "best_ask": snapshot.best_ask,
                "midpoint": snapshot.midpoint,
                "last_trade_price": snapshot.last_trade_price,
                "resolved": snapshot.resolved,
            }
            for token_id, snapshot in market_cache.as_dict().items()
        },
    }


def replay_user_events(path: Path, *, cfg: AppConfig, order_manager: LiveOrderManager | None = None) -> dict[str, object]:
    order_manager = order_manager or LiveOrderManager(cfg)
    updates = 0
    for event in load_event_file(path):
        if order_manager.apply_user_event(event) is not None:
            updates += 1
    return {
        "applied": updates,
        "orders": [
            {
                "order_id": record.order_id,
                "status": record.status,
                "filled_shares": record.filled_shares,
                "remaining_shares": record.remaining_shares,
            }
            for record in order_manager.records()
        ],
    }


def soak_runtime(
    client,
    *,
    cfg: AppConfig,
    limit: int,
    scan_cfg,
    cycles: int,
    market_events_path: Path | None = None,
    user_events_path: Path | None = None,
    batch_size: int = 1,
) -> dict[str, object]:
    market_events = load_event_file(market_events_path) if market_events_path is not None else []
    user_events = load_event_file(user_events_path) if user_events_path is not None else []
    market_idx = 0
    user_idx = 0
    order_manager = LiveOrderManager(cfg)

    def _stream_hook(*, iteration: int, market_cache: MarketStateCache):
        nonlocal market_idx, user_idx
        for event in market_events[market_idx : market_idx + batch_size]:
            try:
                market_cache.apply(event)
            except ValueError:
                continue
        market_idx += batch_size
        for event in user_events[user_idx : user_idx + batch_size]:
            order_manager.apply_user_event(event)
        user_idx += batch_size

    result = run_runtime_loop(
        client,
        cfg=cfg,
        limit=limit,
        scan_cfg=scan_cfg,
        cycles=cycles,
        sleep_seconds=0.0,
        stream_hook=_stream_hook,
    )
    result["market_events_consumed"] = min(market_idx, len(market_events))
    result["user_events_consumed"] = min(user_idx, len(user_events))
    return result
