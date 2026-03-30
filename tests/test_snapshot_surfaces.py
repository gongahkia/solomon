from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest
from typer.testing import CliRunner

from stonks_cli.cli import app


def _configure_csv_snapshot_env(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    csv_path = tmp_path / "prices.csv"

    dates = pd.date_range(end=date.today().isoformat(), periods=90, freq="D")
    df = pd.DataFrame(
        {
            "date": dates,
            "open": [100.0 + i * 0.1 for i in range(len(dates))],
            "high": [101.0 + i * 0.1 for i in range(len(dates))],
            "low": [99.0 + i * 0.1 for i in range(len(dates))],
            "close": [100.0 + i * 0.1 for i in range(len(dates))],
            "volume": [1000 + i for i in range(len(dates))],
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


def test_snapshot_cli_json_surface(monkeypatch, tmp_path):
    _configure_csv_snapshot_env(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["snapshot", "--json"])
    assert result.exit_code == 0, result.stdout

    payload = json.loads(result.stdout)
    assert "generated_at" in payload
    assert "tickers" in payload
    assert payload["tickers"][0]["ticker"] == "AAPL.US"


def test_snapshot_mcp_surface(monkeypatch, tmp_path):
    _configure_csv_snapshot_env(monkeypatch, tmp_path)

    try:
        from stonks_cli.mcp_server import get_market_snapshot
    except ImportError as e:
        if "mcp" in str(e):
            pytest.skip("MCP optional dependency not installed")
        raise

    payload = get_market_snapshot()
    assert "generated_at" in payload
    assert "tickers" in payload
    assert payload["tickers"][0]["ticker"] == "AAPL.US"
