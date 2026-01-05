import json
from pathlib import Path

import pytest

from stonks_cli.commands import do_signals_diff
from stonks_cli.storage import save_last_run


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_signals_diff_detects_changes(monkeypatch, tmp_path):
    # Keep state isolated by pointing HOME at tmp.
    monkeypatch.setenv("HOME", str(tmp_path))

    prev_json = tmp_path / "prev.json"
    latest_json = tmp_path / "latest.json"

    _write_json(
        prev_json,
        {
            "results": [
                {"ticker": "AAPL", "action": "SELL", "confidence": 0.40},
                {"ticker": "MSFT", "action": "HOLD", "confidence": 0.55},
            ]
        },
    )
    _write_json(
        latest_json,
        {
            "results": [
                {"ticker": "AAPL", "action": "BUY", "confidence": 0.80},
                # MSFT removed
                {"ticker": "GOOG", "action": "HOLD", "confidence": 0.10},
            ]
        },
    )

    # Oldest first, then newest.
    save_last_run(["AAPL", "MSFT"], tmp_path / "prev.txt", json_path=prev_json)
    save_last_run(["AAPL", "GOOG"], tmp_path / "latest.txt", json_path=latest_json)

    out = do_signals_diff()
    assert out["count"] == 3

    changes = out["changes"]
    tickers = {c["ticker"] for c in changes}
    assert tickers == {"AAPL", "MSFT", "GOOG"}

    kinds = {(c["ticker"], c["kind"]) for c in changes}
    assert ("AAPL", "CHANGED") in kinds
    assert ("MSFT", "REMOVED") in kinds
    assert ("GOOG", "ADDED") in kinds


def test_signals_diff_requires_two_runs(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        do_signals_diff()
