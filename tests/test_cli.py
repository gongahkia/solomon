from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from stonks_cli import cli
from stonks_cli.cli import app
from stonks_cli.plugins import PluginDiscovery, PluginLoadDiagnostic


def test_cli_public_command_contract_excludes_execution() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    for command in (
        "init-profile",
        "import-csv",
        "import-prices",
        "portfolio",
        "transactions",
        "performance",
        "backup-profile",
        "restore-profile",
        "rotate-key",
        "backtest-csv",
        "schedule-render",
        "notify-local",
        "plugins",
        "moomoo-accounts",
        "version",
    ):
        assert command in result.output
    for prohibited in ("unlock", "order", "trade", "submit", "cancel"):
        assert prohibited not in result.output.lower()


def test_cli_initializes_imports_and_reports(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    key = tmp_path / "key"
    result = runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)])
    assert result.exit_code == 0, result.output
    assert len(key.read_bytes()) == 32
    assert key.stat().st_mode & 0o077 == 0
    source = tmp_path / "events.csv"
    source.write_text(
        "account_id,occurred_at,kind,currency,amount\n"
        "main,2026-01-01T00:00:00+00:00,cash_deposit,USD,100\n"
    )
    result = runner.invoke(app, ["import-csv", "personal", str(source)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["portfolio", "personal", "--json"])
    assert result.exit_code == 0, result.output
    assert '"event_count": 1' in result.output


def test_plugins_command_reports_plugin_load_diagnostics(monkeypatch) -> None:
    monkeypatch.setattr(
        cli,
        "discover_with_diagnostics",
        lambda: PluginDiscovery(
            (),
            (PluginLoadDiagnostic("broken", "RuntimeError: fixture load failed"),),
        ),
    )

    result = CliRunner().invoke(app, ["plugins"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["built_in"] == ["csv", "moomoo"]
    assert payload["diagnostics"] == [
        {"entry_point": "broken", "error": "RuntimeError: fixture load failed"}
    ]


def test_cli_restores_encrypted_profile_backup(tmp_path: Path, monkeypatch) -> None:
    source_home = tmp_path / "source-home"
    monkeypatch.setenv("STONKS_CLI_HOME", str(source_home))
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0
    source = tmp_path / "events.csv"
    source.write_text(
        "account_id,occurred_at,kind,currency,amount\n"
        "main,2026-01-01T00:00:00+00:00,cash_deposit,USD,100\n"
    )
    assert runner.invoke(app, ["import-csv", "personal", str(source)]).exit_code == 0
    backup = tmp_path / "backup"
    assert runner.invoke(app, ["backup-profile", "personal", str(backup)]).exit_code == 0
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "restore-home"))
    result = runner.invoke(app, ["restore-profile", str(backup)])
    assert result.exit_code == 0, result.output
    assert '"profile": "personal"' in result.output
    result = runner.invoke(app, ["portfolio", "personal", "--json"])
    assert result.exit_code == 0, result.output
    assert '"event_count": 1' in result.output
