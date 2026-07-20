from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from stonks_cli.cli import app


def test_cli_initializes_imports_and_reports(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    key = tmp_path / "key"
    result = runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)])
    assert result.exit_code == 0, result.output
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
