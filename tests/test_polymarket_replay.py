from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from stonks_cli.config import AppConfig, PolymarketConfig
from stonks_cli.polymarket.client import PolymarketClient
from stonks_cli.polymarket.execution import ExecutionOrder
from stonks_cli.polymarket.lifecycle import LiveOrderManager, build_live_order_request
from stonks_cli.polymarket.models import LiveMarketSnapshot
from stonks_cli.polymarket.replay import replay_market_events, replay_user_events, soak_runtime
from stonks_cli.polymarket.scanner import StructuralScanConfig


class _Resp:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _Session:
    def get(self, url: str, params=None, timeout: float = 15.0):
        if "gamma-api" in url:
            payload = [
                {
                    "id": "1",
                    "question": "Will BTC close higher today?",
                    "slug": "btc-higher",
                    "condition_id": "cond-1",
                    "active": True,
                    "closed": False,
                    "liquidityNum": 250000,
                    "volumeNum": 900000,
                    "endDate": (datetime.now(UTC) + timedelta(hours=10)).isoformat().replace("+00:00", "Z"),
                    "tokens": [
                        {"token_id": "YES1", "outcome": "YES", "price": 0.58},
                        {"token_id": "NO1", "outcome": "NO", "price": 0.43},
                    ],
                }
            ]
            return _Resp(json.dumps(payload))
        if "midpoint" in url:
            return _Resp(json.dumps({"midpoint": "0.59"}))
        return _Resp(json.dumps({"bids": [{"price": 0.57, "size": 5000}], "asks": [{"price": 0.59, "size": 5000}]}))


def _scan_cfg() -> StructuralScanConfig:
    return StructuralScanConfig(
        min_market_liquidity_usd=50000,
        min_book_depth_usd=500,
        min_hours_to_resolution=4,
        max_hours_to_resolution=168,
        require_active=True,
    )


def test_replay_market_events_applies_snapshots(tmp_path):
    path = tmp_path / "market.jsonl"
    path.write_text(
        json.dumps({"event_type": "best_bid_ask", "asset_id": "YES1", "best_bid": "0.41", "best_ask": "0.43"}) + "\n"
        + json.dumps({"event_type": "last_trade_price", "asset_id": "YES1", "price": "0.42"}) + "\n",
        encoding="utf-8",
    )

    result = replay_market_events(path)

    assert result["applied"] == 2
    assert result["snapshots"]["YES1"]["last_trade_price"] == 0.42


def test_replay_user_events_updates_orders(monkeypatch, tmp_path):
    from stonks_cli.polymarket import lifecycle

    monkeypatch.setattr(lifecycle, "default_state_dir", lambda: tmp_path)

    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=False))
    manager = LiveOrderManager(cfg)
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
    )
    path = tmp_path / "user.json"
    path.write_text(json.dumps([{"order_id": "order-1", "status": "FILLED", "filled_size": 12, "remaining_size": 0}]), encoding="utf-8")

    result = replay_user_events(path, cfg=cfg, order_manager=manager)

    assert result["applied"] == 1
    assert result["orders"][0]["status"] == "FILLED"


def test_soak_runtime_consumes_recorded_events(monkeypatch, tmp_path):
    from stonks_cli.polymarket import guards, journal, lifecycle, storage

    monkeypatch.setattr(storage, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(journal, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(guards, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(lifecycle, "default_state_dir", lambda: tmp_path)

    market_path = tmp_path / "market.jsonl"
    market_path.write_text(
        json.dumps({"event_type": "best_bid_ask", "asset_id": "YES1", "best_bid": "0.61", "best_ask": "0.63"}) + "\n",
        encoding="utf-8",
    )

    result = soak_runtime(
        PolymarketClient(session=_Session()),
        cfg=AppConfig(polymarket=PolymarketConfig(enabled=True, paper=True, auto_trade_enabled=False)),
        limit=1,
        scan_cfg=_scan_cfg(),
        cycles=1,
        market_events_path=market_path,
        batch_size=1,
    )

    assert result["market_events_consumed"] == 1
    assert result["final_status"]["state"] == "idle"
