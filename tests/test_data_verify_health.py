from __future__ import annotations

import json

import pandas as pd

from stonks_cli.commands import do_data_verify


def test_data_verify_flags_missing_close(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    csv_path = tmp_path / "prices.csv"

    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    df = pd.DataFrame(
        {
            "date": dates,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            # intentionally missing close
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
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    out = do_data_verify(None)
    assert out["AAPL.US"].startswith("missing_columns")
