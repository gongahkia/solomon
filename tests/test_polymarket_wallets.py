from __future__ import annotations

import csv

from stonks_cli.polymarket.wallets import (
    import_wallet_trades,
    load_wallet_import_summary,
    load_wallet_market_signals,
    load_wallet_targets,
    rank_wallets,
)


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
