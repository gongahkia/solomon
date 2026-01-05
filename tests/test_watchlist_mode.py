import json

import pandas as pd

from stonks_cli.commands import do_watchlist_analyze, do_watchlist_set


def test_watchlist_analyze_runs_on_named_set(monkeypatch, tmp_path):
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
                "tickers": [],
                "data": {"provider": "csv", "csv_path": str(csv_path), "cache_ttl_seconds": 0},
                "risk": {"min_history_days": 60},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    do_watchlist_set("tech", ["AAPL.US"])
    artifacts = do_watchlist_analyze("tech", out_dir=out_dir, json_out=True, report_name="report_latest.txt")
    assert artifacts.report_path.exists()
    assert artifacts.report_path.name == "report_latest.txt"
    assert artifacts.json_path is not None and artifacts.json_path.exists()
    assert "AAPL.US" in artifacts.report_path.read_text(encoding="utf-8")
