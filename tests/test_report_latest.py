from __future__ import annotations

import json

import pandas as pd

from stonks_cli.commands import do_analyze_artifacts, do_report_latest


def test_report_latest_returns_json_path_when_available(monkeypatch, tmp_path):
    # Keep state isolated by pointing HOME at tmp.
    monkeypatch.setenv("HOME", str(tmp_path))

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
            "ticker": "AAPL",
        }
    )
    df.to_csv(csv_path, index=False)

    cfg_path.write_text(
        json.dumps(
            {
                "tickers": ["AAPL"],
                "data": {"provider": "csv", "csv_path": str(csv_path), "cache_ttl_seconds": 0},
                "risk": {"min_history_days": 60},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    artifacts = do_analyze_artifacts(None, out_dir=out_dir, json_out=True)
    assert artifacts.json_path is not None

    latest = do_report_latest(include_json=True)
    assert latest["report_path"] == str(artifacts.report_path)
    assert latest["json_path"] == str(artifacts.json_path)
