from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from stonks_cli import cli
from stonks_cli.cli import app
from stonks_cli.market_data import DailyPrice
from stonks_cli.plugins import PluginDiscovery, PluginLoadDiagnostic
from stonks_cli.types import Currency, Instrument


def test_cli_public_command_contract_excludes_execution() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    for command in (
        "init-profile",
        "import-csv",
        "import-prices",
        "import-fx",
        "portfolio",
        "reconciliation",
        "transactions",
        "performance",
        "backup-profile",
        "restore-profile",
        "rotate-key",
        "backtest-csv",
        "strategy-artifacts",
        "strategy-journal",
        "strategy-journal-list",
        "watchlist-add",
        "watchlist-remove",
        "watchlist",
        "refresh-moomoo-prices",
        "refresh-moomoo-quotes",
        "schedule-render",
        "schedule-install",
        "schedule-status",
        "notify-local",
        "notify-telegram",
        "paper-deposit",
        "paper-open",
        "paper-close",
        "paper-portfolio",
        "ml-train",
        "ml-predict",
        "ml-rank",
        "research-candidates",
        "research-artifacts",
        "llm-configure",
        "llm-status",
        "llm-chat",
        "llm-news-summary",
        "llm-explain-candidates",
        "llm-agent-prompt",
        "scan-alerts",
        "monitor",
        "plugins",
        "enable-provider",
        "disable-provider",
        "moomoo-accounts",
        "moomoo-sync",
        "moomoo-cash-flows",
        "moomoo-probe",
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


def test_cli_updates_enabled_provider_list(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0

    result = runner.invoke(app, ["disable-provider", "personal", "moomoo"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["providers"] == ["csv"]
    result = runner.invoke(app, ["enable-provider", "personal", "moomoo"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["providers"] == ["csv", "moomoo"]


def test_cli_configures_local_llm_and_keeps_agent_wrappers_manual(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0

    result = runner.invoke(
        app, ["llm-configure", "personal", "ollama", "tiny", "--ollama-local-only"]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["llm"]["provider"] == "ollama"
    result = runner.invoke(app, ["llm-agent-prompt", "codex", "What is inflation?"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["execution"] == "manual_only"
    assert payload["shell_command"].startswith("codex exec")


def test_cli_manages_encrypted_watchlist(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0

    result = runner.invoke(
        app,
        ["watchlist-add", "personal", "SPY", "US", "USD", "--name", "S&P 500"],
    )

    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["watchlist", "personal"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["items"][0]["instrument"] == "US:SPY"


def test_cli_refreshes_moomoo_prices_from_watchlist(tmp_path: Path, monkeypatch) -> None:
    class Provider:
        def daily_prices(self, instruments, start, end):
            assert instruments == (Instrument("SPY", "US", Currency.USD, None),)
            return (DailyPrice(instruments[0], start, "100", "a" * 64),)

    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        cli.MoomooReadOnlyProvider,
        "from_installed_sdk",
        lambda endpoint: Provider(),
    )
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0
    assert runner.invoke(app, ["watchlist-add", "personal", "SPY", "US", "USD"]).exit_code == 0

    result = runner.invoke(app, ["refresh-moomoo-prices", "personal"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["prices"] == 1


def test_cli_sends_telegram_using_environment_token(monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_TELEGRAM_TOKEN", "token")
    monkeypatch.setattr(cli, "notify_telegram", lambda token, chat_id, title, message: True)

    result = CliRunner().invoke(app, ["notify-telegram", "Title", "Message", "--chat-id", "chat"])

    assert result.exit_code == 0, result.output


def test_cli_manages_a_paper_portfolio(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0
    assert runner.invoke(app, ["paper-deposit", "personal", "1000", "USD"]).exit_code == 0
    assert runner.invoke(
        app, ["paper-open", "personal", "SPY", "US", "USD", "2", "100"]
    ).exit_code == 0

    result = runner.invoke(app, ["paper-portfolio", "personal"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["positions"] == {"US:SPY": "2"}


def test_monitor_refreshes_and_delivers_public_price_alerts(tmp_path: Path, monkeypatch) -> None:
    class Provider:
        def daily_prices(self, instruments, start, end):
            return (
                DailyPrice(instruments[0], start, "100", "a" * 64),
                DailyPrice(instruments[0], end, "106", "a" * 64),
            )

    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("STONKS_CLI_TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("STONKS_CLI_TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(cli.MoomooReadOnlyProvider, "from_installed_sdk", lambda endpoint: Provider())
    monkeypatch.setattr(cli, "notify_telegram", lambda token, chat_id, title, message: True)
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0
    assert runner.invoke(app, ["watchlist-add", "personal", "SPY", "US", "USD"]).exit_code == 0

    result = runner.invoke(app, ["monitor", "personal", "--days", "2"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["alerts"][0]["instrument"] == "US:SPY"
    assert payload["telegram_delivered"] is True


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
