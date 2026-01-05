import json

import pandas as pd

from stonks_cli.commands import do_analyze_artifacts


def test_analyze_csv_summary_writes_alongside_report(monkeypatch, tmp_path):
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
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    artifacts = do_analyze_artifacts(
        None,
        out_dir=out_dir,
        json_out=False,
        csv_out=True,
        report_name="report_latest.txt",
    )
    assert artifacts.report_path.exists()

    summary_path = out_dir / "report_latest.csv"
    assert summary_path.exists()
    text = summary_path.read_text(encoding="utf-8")
    assert "ticker,action,confidence,cagr,sharpe,maxdd" in text
    assert "AAPL.US" in text
