from __future__ import annotations

import json

import pandas as pd

from stonks.commands import do_schedule_once


def test_schedule_once_runs_job(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    out_dir = tmp_path / "out"
    csv_path = tmp_path / "prices.csv"

    dates = pd.date_range("2024-01-01", periods=120, freq="D")
    df = pd.DataFrame(
        {
            "date": dates,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": [100.0 + (i * 0.1) for i in range(len(dates))],
            "volume": 1000,
            "ticker": "AAPL.US",
        }
    )
    df.to_csv(csv_path, index=False)

    cfg_path.write_text(
        json.dumps(
            {
                "tickers": ["AAPL.US"],
                "data": {"provider": "csv", "csv_path": str(csv_path), "cache_ttl_seconds": 0},
                "risk": {"min_history_days": 60},
                "schedule": {"cron": "0 17 * * 1-5"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STONKS_CONFIG", str(cfg_path))

    report_path = do_schedule_once(out_dir=out_dir)
    assert report_path.exists()
    assert "report_" in report_path.name
