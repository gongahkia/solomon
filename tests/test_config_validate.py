from __future__ import annotations

import json

from typer.testing import CliRunner

from stonks_cli.cli import app
from stonks_cli.commands import do_config_validate
from stonks_cli.errors import ExitCodes


def test_config_validate_reports_tickers_and_strategy(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps({"tickers": ["aapl"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))
    out = do_config_validate()
    assert out["valid"] is True
    assert out["errors"] == []
    assert out["schema_version"] == 2
    assert out["tickers"] == ["aapl"]
    assert "strategy" in out
    assert out["vnext_execution_mode"] == "disabled"
    assert out["vnext_broker_read_only"] is True


def test_config_migrate_cli_command(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")

    result = CliRunner().invoke(app, ["config", "migrate", "--path", str(path)])

    assert result.exit_code == 0
    assert "Config migrated" in result.output
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2


def test_config_validate_cli_emits_secret_safe_failure_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"vnext": {"features": {"broker_data": "secret-value"}}}), encoding="utf-8")

    result = CliRunner().invoke(app, ["config", "validate", "--path", str(path)])

    assert result.exit_code == ExitCodes.BAD_CONFIG
    assert json.loads(result.output) == {"valid": False, "errors": [{"code": "schema_validation_error"}]}
    assert "secret-value" not in result.output
