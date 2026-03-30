from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd

from stonks_cli.commands import do_market_snapshot


def test_market_snapshot_includes_core_sections(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    csv_path = tmp_path / "prices.csv"

    # End date intentionally stale so snapshot can surface freshness warnings.
    end = date.today() - timedelta(days=7)
    dates = pd.date_range(end=end.isoformat(), periods=90, freq="D")
    df = pd.DataFrame(
        {
            "date": dates,
            "open": [100.0 + i * 0.2 for i in range(len(dates))],
            "high": [101.0 + i * 0.2 for i in range(len(dates))],
            "low": [99.0 + i * 0.2 for i in range(len(dates))],
            "close": [100.0 + i * 0.2 for i in range(len(dates))],
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

    out = do_market_snapshot()
    assert "generated_at" in out
    assert "tickers" in out
    assert "alerts" in out
    assert "top_movers" in out
    assert "unusual_volume" in out

    tickers = out["tickers"]
    assert len(tickers) == 1
    first = tickers[0]
    assert first["ticker"] == "AAPL.US"
    assert isinstance(first["stale"], bool)
    assert first["last_data_date"] is not None
    assert first["data_age_days"] is not None

    assert "AAPL.US" in out["stale_tickers"]
    assert out["signals_diff"] is None
