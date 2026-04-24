from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from stonks_cli.config import AppConfig, PolymarketConfig
from stonks_cli.polymarket.client import PolymarketClient
from stonks_cli.polymarket.paper import init_paper_account
from stonks_cli.polymarket.runtime import run_runtime_cycle
from stonks_cli.polymarket.scanner import StructuralScanConfig
from stonks_cli.polymarket.wallets import WalletMarketSignal, save_wallet_market_signals


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
            return _Resp(json.dumps({"midpoint": "0.66"}))
        return _Resp(
            json.dumps(
                {
                    "bids": [{"price": 0.57, "size": 5000}],
                    "asks": [{"price": 0.59, "size": 5000}],
                }
            )
        )


def test_runtime_cycle_can_auto_trade_in_paper_mode(monkeypatch, tmp_path):
    from stonks_cli.polymarket import paper, storage, wallets

    monkeypatch.setattr(storage, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(paper, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(wallets, "default_state_dir", lambda: tmp_path)

    init_paper_account(1000.0)
    save_wallet_market_signals(
        [
            WalletMarketSignal(
                market_id="1",
                outcome="YES",
                wallet_count=3,
                trade_count=10,
                net_volume=500.0,
                gross_volume=300.0,
            )
        ]
    )

    client = PolymarketClient(session=_Session())
    cfg = AppConfig(
        polymarket=PolymarketConfig(
            enabled=True,
            paper=True,
            auto_trade_enabled=True,
            auto_trade_min_score=1.0,
            auto_trade_min_target_wallets=1,
            max_position_fraction=0.10,
            paper_starting_cash=1000.0,
        )
    )
    scan_cfg = StructuralScanConfig(
        min_market_liquidity_usd=50000,
        min_book_depth_usd=500,
        min_hours_to_resolution=4,
        max_hours_to_resolution=168,
        require_active=True,
    )

    result = run_runtime_cycle(client, cfg=cfg, limit=1, scan_cfg=scan_cfg)

    assert len(result["queue"]) == 1
    assert len(result["actions"]) == 1
    assert result["status"]["state"] == "traded"
    assert result["status"]["open_positions"] == 1


def test_runtime_cycle_can_auto_exit_position_not_in_scan_queue(monkeypatch, tmp_path):
    from stonks_cli.polymarket import journal, paper, storage, wallets

    monkeypatch.setattr(storage, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(paper, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(wallets, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(journal, "default_state_dir", lambda: tmp_path)

    init_paper_account(1000.0)
    paper.paper_buy(
        token_id="EXIT1",
        market_id="9",
        slug="exit-market",
        outcome="YES",
        shares=100.0,
        price=0.50,
        target_price=0.60,
        stop_price=0.42,
    )

    client = PolymarketClient(session=_Session())
    cfg = AppConfig(
        polymarket=PolymarketConfig(
            enabled=True,
            paper=True,
            auto_trade_enabled=False,
            auto_exit_enabled=True,
        )
    )
    scan_cfg = StructuralScanConfig(
        min_market_liquidity_usd=50000,
        min_book_depth_usd=500,
        min_hours_to_resolution=4,
        max_hours_to_resolution=168,
        require_active=True,
    )

    result = run_runtime_cycle(client, cfg=cfg, limit=1, scan_cfg=scan_cfg)

    assert len(result["actions"]) == 1
    assert result["actions"][0]["action"] == "SELL"
    assert result["status"]["open_positions"] == 0
