from __future__ import annotations

import json

import pandas as pd

from stonks_cli.commands import do_config_validate


def test_config_validate_reports_normalized_tickers_and_providers(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    csv_path = tmp_path / "prices.csv"

    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    df = pd.DataFrame(
        {
            "date": dates,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000,
            "ticker": "AAPL",
        }
    )
    df.to_csv(csv_path, index=False)

    cfg_path.write_text(
        json.dumps(
            {
                "tickers": ["aapl"],
                "data": {"provider": "csv", "csv_path": str(csv_path), "cache_ttl_seconds": 0},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))
    out = do_config_validate()

    assert out["tickers"] == ["AAPL.US"]
    assert out["providers"]["AAPL.US"] in {"CsvProvider"}
