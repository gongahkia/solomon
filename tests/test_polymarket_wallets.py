from __future__ import annotations

import csv
from pathlib import Path

from stonks_cli.polymarket.wallets import (
    detect_whale_trades,
    import_wallet_trades,
    load_wallet_import_summary,
    load_wallet_market_signals,
    load_wallet_targets,
    rank_wallets,
)


def test_detect_whale_trades_filters_by_notional(tmp_path: Path):
    csv_path = tmp_path / "trades.csv"
    csv_path.write_text(
        "maker,market_id,nonusdc_side,maker_direction,price,token_amount,timestamp\n"
        "0xaaa,m1,YES,BUY,0.4,30000,t1\n"
        "0xbbb,m1,YES,SELL,0.42,500,t2\n"
        "0xccc,m2,NO,BUY,0.1,50000,t3\n",
        encoding="utf-8",
    )
    whales = detect_whale_trades(csv_path=csv_path, min_notional_usd=5000.0, limit=10)
    notionals = sorted(w.notional for w in whales)
    assert notionals == [5000.0, 12000.0]
    assert all(w.notional >= 5000.0 for w in whales)


def test_detect_whale_trades_filters_by_market(tmp_path: Path):
    csv_path = tmp_path / "trades.csv"
    csv_path.write_text(
        "maker,market_id,nonusdc_side,maker_direction,price,token_amount\n"
        "0xaaa,m1,YES,BUY,0.4,30000\n"
        "0xccc,m2,NO,BUY,0.1,50000\n",
        encoding="utf-8",
    )
    whales = detect_whale_trades(csv_path=csv_path, min_notional_usd=1000.0, limit=10, market_id="m2")
    assert len(whales) == 1
    assert whales[0].market_id == "m2"


def _write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "timestamp",
                "market_id",
                "maker",
                "taker",
                "nonusdc_side",
                "maker_direction",
                "taker_direction",
                "price",
                "usd_amount",
                "token_amount",
                "transactionHash",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def test_import_wallet_trades_persists_summary(monkeypatch, tmp_path):
    from stonks_cli.polymarket import wallets

    monkeypatch.setattr(wallets, "default_state_dir", lambda: tmp_path)
    csv_path = tmp_path / "trades.csv"
    _write_csv(
        csv_path,
        [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "market_id": "1",
                "maker": "0xabc",
                "taker": "0xdef",
                "nonusdc_side": "YES",
                "maker_direction": "BUY",
                "taker_direction": "SELL",
                "price": "0.40",
                "usd_amount": "40",
                "token_amount": "100",
                "transactionHash": "0x1",
            }
        ],
    )

    summary = import_wallet_trades(csv_path)
    loaded = load_wallet_import_summary()

    assert summary.row_count == 1
    assert summary.wallet_count == 1
    assert loaded is not None
    assert loaded.source_path == str(csv_path.resolve())


def test_rank_wallets_uses_fifo_realized_pnl_fallback(monkeypatch, tmp_path):
    from stonks_cli.polymarket import wallets

    monkeypatch.setattr(wallets, "default_state_dir", lambda: tmp_path)
    csv_path = tmp_path / "trades.csv"
    _write_csv(
        csv_path,
        [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "market_id": "1",
                "maker": "0xgood",
                "taker": "0xdef",
                "nonusdc_side": "YES",
                "maker_direction": "BUY",
                "taker_direction": "SELL",
                "price": "0.40",
                "usd_amount": "40",
                "token_amount": "100",
                "transactionHash": "0x1",
            },
            {
                "timestamp": "2026-01-01T01:00:00Z",
                "market_id": "1",
                "maker": "0xgood",
                "taker": "0xdef",
                "nonusdc_side": "YES",
                "maker_direction": "SELL",
                "taker_direction": "BUY",
                "price": "0.60",
                "usd_amount": "60",
                "token_amount": "100",
                "transactionHash": "0x2",
            },
            {
                "timestamp": "2026-01-01T02:00:00Z",
                "market_id": "2",
                "maker": "0xbad",
                "taker": "0xdef",
                "nonusdc_side": "YES",
                "maker_direction": "BUY",
                "taker_direction": "SELL",
                "price": "0.70",
                "usd_amount": "70",
                "token_amount": "100",
                "transactionHash": "0x3",
            },
            {
                "timestamp": "2026-01-01T03:00:00Z",
                "market_id": "2",
                "maker": "0xbad",
                "taker": "0xdef",
                "nonusdc_side": "YES",
                "maker_direction": "SELL",
                "taker_direction": "BUY",
                "price": "0.50",
                "usd_amount": "50",
                "token_amount": "100",
                "transactionHash": "0x4",
            },
        ],
    )

    import_wallet_trades(csv_path)
    targets = rank_wallets(min_trades=2, min_win_rate=0.60, limit=10)
    saved = load_wallet_targets()

    assert len(targets) == 1
    assert targets[0].wallet == "0xgood"
    assert round(targets[0].realized_pnl, 2) == 20.00
    assert round(targets[0].win_rate, 2) == 1.00
    assert len(saved) == 1
    assert saved[0].wallet == "0xgood"
    signals = load_wallet_market_signals()
    assert len(signals) == 1
    assert signals[0].market_id == "1"
    assert signals[0].outcome == "YES"
    assert signals[0].wallet_count == 1
