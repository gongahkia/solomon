from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from stonks_cli.config import AppConfig, PolymarketConfig
from stonks_cli.polymarket.client import PolymarketClient
from stonks_cli.polymarket.runtime import run_runtime_loop, run_structural_scan_once
from stonks_cli.polymarket.scanner import StructuralScanConfig
from stonks_cli.polymarket.stream import MarketStateCache


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
        return _Resp(
            json.dumps(
                {
                    "bids": [{"price": 0.57, "size": 5000}],
                    "asks": [{"price": 0.59, "size": 5000}],
                }
            )
        )


def _scan_cfg() -> StructuralScanConfig:
    return StructuralScanConfig(
        min_market_liquidity_usd=50000,
        min_book_depth_usd=500,
        min_hours_to_resolution=4,
        max_hours_to_resolution=168,
        require_active=True,
    )


def test_run_structural_scan_once_applies_market_cache(monkeypatch, tmp_path):
    from stonks_cli.polymarket import journal, storage

    monkeypatch.setattr(storage, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(journal, "default_state_dir", lambda: tmp_path)
    client = PolymarketClient(session=_Session())
    cache = MarketStateCache()
    cache.apply({"event_type": "best_bid_ask", "asset_id": "YES1", "best_bid": "0.65", "best_ask": "0.67"})

    _, scans = run_structural_scan_once(client, limit=1, cfg=_scan_cfg(), paper=True, market_cache=cache)

    assert scans[0].midpoint == 0.66
    assert "stream_midpoint" in scans[0].reasons


def test_run_runtime_loop_runs_multiple_iterations(monkeypatch, tmp_path):
    from stonks_cli.polymarket import storage

    monkeypatch.setattr(storage, "default_state_dir", lambda: tmp_path)
    client = PolymarketClient(session=_Session())
    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=True, auto_trade_enabled=False))

    def _stream_hook(*, iteration: int, market_cache: MarketStateCache):
        price = "0.61" if iteration == 1 else "0.63"
        market_cache.apply({"event_type": "best_bid_ask", "asset_id": "YES1", "best_bid": price, "best_ask": price})

    result = run_runtime_loop(
        client,
        cfg=cfg,
        limit=1,
        scan_cfg=_scan_cfg(),
        cycles=2,
        sleep_seconds=0.0,
        stream_hook=_stream_hook,
    )

    assert result["cycles"] == 2
    assert len(result["iterations"]) == 2
    assert result["final_status"]["state"] == "idle"
