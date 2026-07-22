from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from typer.testing import CliRunner

from stonks_cli import cli
from stonks_cli.cli import app
from stonks_cli.market_data import (
    DailyPrice,
    QuoteQuality,
    QuoteSnapshot,
    QuoteStatus,
    archive_and_store_quote_snapshots,
    store_instrument_masters,
)
from stonks_cli.moomoo import OpenDSDKStatus
from stonks_cli.plugins import PluginDiscovery, PluginLoadDiagnostic
from stonks_cli.storage import EncryptedLedger
from stonks_cli.types import (
    AssetClass,
    Currency,
    ETFClassification,
    GICSSector,
    Instrument,
    InstrumentMaster,
    ListingStatus,
)


def test_cli_public_command_contract_excludes_execution() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    for command in (
        "init-profile",
        "import-csv",
        "import-history",
        "import-prices",
        "import-fx",
        "portfolio",
        "daily-report",
        "holdings",
        "cash",
        "exposure",
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
        "watchlist-configure",
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
        "plugins-validate",
        "enable-provider",
        "disable-provider",
        "dividend-configure",
        "moomoo-accounts",
        "moomoo-dividends",
        "moomoo-dividend-status",
        "moomoo-map-dividend",
        "moomoo-sync",
        "moomoo-cash-flows",
        "moomoo-probe",
        "moomoo-sdk-status",
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
    result = runner.invoke(app, ["daily-report", "personal"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["event_count"] == 1
    result = runner.invoke(app, ["import-history", "personal"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["source_hashes"]
    result = runner.invoke(app, ["holdings", "personal"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["positions"] == []
    result = runner.invoke(app, ["cash", "personal"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["balances"] == [
        {"account": "csv:main", "currency": "USD", "amount": "100"}
    ]
    result = runner.invoke(app, ["exposure", "personal"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["exposure"] == [
        {"currency": "USD", "cash": "100", "market_value": "0", "exposure": "100"}
    ]


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


def test_cli_configures_explicit_dividend_credit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0

    result = runner.invoke(
        app,
        [
            "dividend-configure",
            "personal",
            "--allow-explicit-credit",
            "--allow-currency-conversion",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["dividends"] == {
        "allow_explicit_credit": True,
        "allow_currency_conversion": True,
    }


def test_cli_validates_enabled_plugin_contracts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0

    result = runner.invoke(app, ["plugins-validate", "personal"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["profile"] == "personal"
    assert payload["valid"] is True
    assert payload["enabled"] == [
        {"identifier": "csv", "source": "built_in", "valid": True},
        {"identifier": "moomoo", "source": "built_in", "valid": True},
    ]
    assert payload["execution"] == "denied"


def test_cli_reports_sdk_status_without_connecting(monkeypatch) -> None:
    monkeypatch.setattr(
        cli.MoomooReadOnlyProvider,
        "sdk_status",
        staticmethod(lambda: OpenDSDKStatus(False, "9.9", "version_incompatible")),
    )

    result = CliRunner().invoke(app, ["moomoo-sdk-status"])

    assert result.exit_code == 1, result.output
    assert json.loads(result.output) == {
        "available": False,
        "version": "9.9",
        "reason": "version_incompatible",
        "execution": "denied",
    }


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
    result = runner.invoke(app, ["watchlist-configure", "personal", "--restrict-recommendations"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["restriction_enabled"] is True
    result = runner.invoke(app, ["watchlist", "personal"])
    assert result.exit_code == 0, result.output
    assert [entry["action"] for entry in json.loads(result.output)["audit"]] == [
        "added",
        "restriction_enabled",
    ]


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


def test_cli_refreshes_moomoo_quotes_with_fail_closed_status(tmp_path: Path, monkeypatch) -> None:
    class Provider:
        def market_snapshots(self, instruments, observed_at):
            return (
                QuoteSnapshot(
                    instruments[0],
                    None,
                    observed_at,
                    QuoteQuality.UNKNOWN,
                    "a" * 64,
                    status=QuoteStatus.UNAVAILABLE,
                    order_book_status="unavailable",
                ),
            )

    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cli.MoomooReadOnlyProvider, "from_installed_sdk", lambda endpoint: Provider())
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0
    assert runner.invoke(app, ["watchlist-add", "personal", "SPY", "US", "USD"]).exit_code == 0

    result = runner.invoke(app, ["refresh-moomoo-quotes", "personal"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["quote_statuses"] == {"unavailable": 1}


def test_cli_portfolio_reports_quote_status_separately_from_value(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0
    events = tmp_path / "events.csv"
    events.write_text(
        "account_id,occurred_at,kind,currency,amount,quantity,symbol,market,instrument_currency\n"
        "main,2026-01-02T00:00:00+00:00,buy,USD,100,1,SPY,US,USD\n"
    )
    prices = tmp_path / "prices.csv"
    prices.write_text("date,symbol,market,currency,close\n2026-01-02,SPY,US,USD,100\n")
    assert runner.invoke(app, ["import-csv", "personal", str(events)]).exit_code == 0
    assert runner.invoke(app, ["import-prices", "personal", str(prices)]).exit_code == 0
    ledger = EncryptedLedger(cli._profile("personal", key))
    store_instrument_masters(
        ledger,
        (
            InstrumentMaster(
                "US:SPY",
                "ARCA",
                "US",
                Currency.USD,
                AssetClass.ETF,
                "US.SPY",
                ListingStatus.LISTED,
                "issuer-2026-01",
                "a" * 64,
                ETFClassification.BROAD_DIVERSIFIED,
                "issuer-2026-01",
                sector=GICSSector.INFORMATION_TECHNOLOGY,
                sector_version="gics-2025",
                sector_source_hash="b" * 64,
            ),
        ),
    )
    instrument = Instrument("SPY", "US", Currency.USD)
    delayed = QuoteSnapshot(
        instrument,
        Decimal("105"),
        datetime(2026, 1, 2, 15, 1, tzinfo=UTC),
        QuoteQuality.DELAYED,
        "b" * 64,
        "2026-01-02 10:00:00",
        QuoteStatus.DELAYED,
        datetime(2026, 1, 2, 15, tzinfo=UTC),
    )
    archive_and_store_quote_snapshots(ledger, (delayed,))

    result = runner.invoke(app, ["portfolio", "personal", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["quote_snapshots"]["US:SPY"]["status"] == "delayed"
    assert payload["quote_snapshots"]["US:SPY"]["price"] is None
    assert payload["valuation_price_sources"]["US:SPY"] == "daily_close"
    assert payload["market_values_by_currency"]["USD"]["csv:main:US:SPY"] == "100"
    assert payload["asset_class_allocation_by_currency"] == {"USD": {"etf": "1"}}
    assert payload["sector_concentration_by_currency"] == {
        "USD": {"allocation": {"information_technology": "1"}, "hhi": "1"}
    }


def test_cli_performance_attributes_dividends_and_fees_by_currency(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0
    source = tmp_path / "events.csv"
    source.write_text(
        "account_id,occurred_at,kind,currency,amount,quantity,symbol,market,fee\n"
        "main,2026-01-01T00:00:00+00:00,cash_deposit,USD,20,,,,\n"
        "main,2026-01-02T00:00:00+00:00,buy,USD,10,1,SPY,US,1\n"
        "main,2026-01-03T00:00:00+00:00,dividend,USD,5,,SPY,US,\n"
        "main,2026-01-04T00:00:00+00:00,fee,USD,2,,,,\n"
    )
    assert runner.invoke(app, ["import-csv", "personal", str(source)]).exit_code == 0

    result = runner.invoke(app, ["performance", "personal"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["dividend_and_fee_attribution"] == {
        "USD": {
            "dividends": "5",
            "standalone_fees": "2",
            "trade_fees": "1",
            "fees": "3",
            "net_return_contribution": "2",
        }
    }


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
