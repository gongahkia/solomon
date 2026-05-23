from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from stonks_cli.cli import app
from stonks_cli.whalemirror.capture_analysis import analyze_capture_archive


def test_analyze_capture_archive_writes_reports(tmp_path: Path):
    _write_capture_archive(tmp_path)

    result = analyze_capture_archive(capture_dir=tmp_path, target_seconds=120, top_limit=5)

    summary = result["summary"]
    assert Path(result["analysis_json_path"]).exists()
    assert Path(result["analysis_report_path"]).exists()
    assert Path(result["executive_summary_path"]).exists()
    assert summary["normalized"]["line_count"] == 2
    assert summary["normalized"]["unique_trade_events"] == 1
    assert summary["normalized"]["unique_wallets"] == 2
    assert summary["projection"]["projected_target_normalized_rows"] == 4
    assert "does not satisfy the formal 7-day" in Path(result["executive_summary_path"]).read_text(encoding="utf-8")


def test_ingest_analyze_cli_uses_existing_archive(tmp_path: Path):
    _write_capture_archive(tmp_path)

    result = CliRunner().invoke(app, ["whalemirror", "ingest", "analyze", "--capture-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert "executive_summary_path" in result.output
    assert (tmp_path / "partial-capture-analysis.md").exists()


def _write_capture_archive(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    raw_rows = [
        {
            "received_at_utc": "2026-05-17T00:00:00Z",
            "raw": {
                "channel": "trades",
                "data": [
                    {
                        "coin": "BTC",
                        "px": "65000",
                        "sz": "0.01",
                        "time": 1770000000000,
                        "tid": 1,
                        "users": ["0xaaa", "0xbbb"],
                    }
                ],
            },
        }
    ]
    normalized_rows = [
        {
            "venue": "hyperliquid",
            "trade_id": "1770000000000:BTC:1:buy",
            "wallet": "0xaaa",
            "market": "BTC-PERP",
            "asset": "BTC",
            "side": "buy",
            "price": 65000.0,
            "size": 0.01,
            "notional_usd": 650.0,
            "observed_at": "2026-05-17T00:00:00Z",
            "raw": {},
        },
        {
            "venue": "hyperliquid",
            "trade_id": "1770000000000:BTC:1:sell",
            "wallet": "0xbbb",
            "market": "BTC-PERP",
            "asset": "BTC",
            "side": "sell",
            "price": 65000.0,
            "size": 0.01,
            "notional_usd": 650.0,
            "observed_at": "2026-05-17T00:01:00Z",
            "raw": {},
        },
    ]
    health = {
        "source": "live_capture",
        "started_at_utc": "2026-05-17T00:00:00Z",
        "updated_at_utc": "2026-05-17T00:01:00Z",
        "duration_seconds": 60.0,
        "final_status": "running",
        "health": {
            "messages_received": 1,
            "decoded_events": 1,
            "decoded_trades": 2,
            "malformed_messages": 0,
            "dropped_messages": 0,
            "reconnects": 0,
            "last_error": None,
        },
        "runtime": {"os": "Linux"},
    }
    _write_jsonl(path / "hyperliquid-raw.jsonl", raw_rows)
    _write_jsonl(path / "hyperliquid-normalized.jsonl", normalized_rows)
    (path / "capture-health.json").write_text(json.dumps(health), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
