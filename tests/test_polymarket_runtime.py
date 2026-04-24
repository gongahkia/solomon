from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from stonks_cli.polymarket.client import PolymarketClient
from stonks_cli.polymarket.runtime import run_structural_scan_once, runtime_status
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
                    "liquidityNum": 150000,
                    "volumeNum": 900000,
                    "endDate": (datetime.now(UTC) + timedelta(hours=10)).isoformat().replace("+00:00", "Z"),
                    "tokens": [
                        {"token_id": "YES1", "outcome": "Yes", "price": 0.58},
                        {"token_id": "NO1", "outcome": "No", "price": 0.43},
                    ],
                }
            ]
            return _Resp(json.dumps(payload))
        return _Resp(
            json.dumps(
                {
                    "bids": [{"price": 0.57, "size": 5000}],
                    "asks": [{"price": 0.59, "size": 5000}],
                }
            )
        )


def test_run_structural_scan_once_persists_status(monkeypatch, tmp_path):
    from stonks_cli.polymarket import storage

    monkeypatch.setattr(storage, "default_state_dir", lambda: tmp_path)

    client = PolymarketClient(session=_Session())
    cfg = StructuralScanConfig(
        min_market_liquidity_usd=50000,
        min_book_depth_usd=500,
        min_hours_to_resolution=4,
        max_hours_to_resolution=168,
        require_active=True,
    )

    status, scans = run_structural_scan_once(client, limit=1, cfg=cfg, paper=True)

    assert status.last_scan_count == 1
    assert status.last_pass_count == 1
    assert len(scans) == 1

    persisted = runtime_status()
    assert persisted.state == "idle"
    assert persisted.paper is True
    assert persisted.last_pass_count == 1
