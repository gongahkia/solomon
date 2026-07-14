from __future__ import annotations

import json

from stonks_cli.commands import do_config_validate


def test_config_validate_reports_tickers_and_strategy(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps({"tickers": ["aapl"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))
    out = do_config_validate()
    assert out["schema_version"] == 2
    assert out["tickers"] == ["aapl"]
    assert "strategy" in out
    assert out["vnext_execution_mode"] == "disabled"
    assert out["vnext_broker_read_only"] is True
