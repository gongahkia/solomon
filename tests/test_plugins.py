from __future__ import annotations

import json

import pandas as pd

from stonks_cli.commands import do_analyze_artifacts


def test_plugin_strategy_is_loaded_and_used(monkeypatch, tmp_path):
    plugin_path = tmp_path / "my_plugin.py"
    plugin_path.write_text(
        "from stonks_cli.analysis.strategy import Recommendation\n"
        "def plugin_buy(df):\n"
        "    return Recommendation(action='BUY_DCA', confidence=0.99, rationale='plugin')\n"
        "STONKS_STRATEGIES = {'plugin_buy': plugin_buy}\n",
        encoding="utf-8",
    )

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
                "plugins": [str(plugin_path)],
                "strategy": "plugin_buy",
                "data": {"provider": "csv", "csv_path": str(csv_path), "cache_ttl_seconds": 0},
                "risk": {"min_history_days": 60},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    artifacts = do_analyze_artifacts(None, out_dir=out_dir, json_out=False, sandbox=True)
    report_txt = artifacts.report_path.read_text(encoding="utf-8")
    assert "BUY_DCA" in report_txt
    assert "plugin" in report_txt
