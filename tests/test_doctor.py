from __future__ import annotations

import json

import pandas as pd

from stonks_cli.commands import do_doctor


def test_doctor_includes_paths_provider_and_plugins(monkeypatch, tmp_path):
    # Keep state/cache dirs isolated.
    monkeypatch.setenv("HOME", str(tmp_path))

    cfg_path = tmp_path / "config.json"
    csv_path = tmp_path / "prices.csv"

    dates = pd.date_range("2024-01-01", periods=5, freq="D")
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
                "tickers": ["AAPL"],
                "data": {"provider": "csv", "csv_path": str(csv_path), "cache_ttl_seconds": 0},
                "plugins": ["/nonexistent/plugin.py"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    out = do_doctor()
    assert "config_path" in out
    assert "cache_dir" in out
    assert "state_dir" in out
    assert out.get("data_provider_type") in {"CsvProvider"}
    assert out.get("plugins_errors") == "1"
