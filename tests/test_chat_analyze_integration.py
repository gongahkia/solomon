from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from stonks.chat.dispatch import ChatState, handle_slash_command


def test_chat_analyze_command_runs_analysis_offline(monkeypatch, tmp_path):
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
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STONKS_CONFIG", str(cfg_path))

    panels: list[tuple[str, str]] = []

    def show_panel(title: str, body: str) -> None:
        panels.append((title, body))

    state = ChatState(messages=[], scheduler=None)

    handle_slash_command("/analyze AAPL.US", state=state, show_panel=show_panel, out_dir=out_dir)

    assert panels, "expected at least one panel output"
    title, body = panels[-1]
    assert title == "analyze"
    assert "Wrote report:" in body

    # Ensure the report exists.
    report_path = body.split("Wrote report:", 1)[1].strip()
    assert (tmp_path / "out").exists()
    assert report_path
    assert Path(report_path).exists()
