from __future__ import annotations

import json
from base64 import b64encode
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from typer.testing import CliRunner

from stonks_cli import cli, telegram_delivery
from stonks_cli.cli import app
from stonks_cli.config import load_profile
from stonks_cli.market_data import (
    DailyPrice,
    FxReferenceRefresh,
    QuoteQuality,
    QuoteSnapshot,
    QuoteStatus,
    archive_and_store_quote_snapshots,
    store_instrument_masters,
)
from stonks_cli.moomoo import OpenDSDKStatus
from stonks_cli.operator import ScheduleStatus
from stonks_cli.plugins import PluginDiscovery, PluginLoadDiagnostic
from stonks_cli.storage import EncryptedLedger
from stonks_cli.terminal_delivery import latest_scheduled_artifact
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
        "import-liquidity",
        "import-fx",
        "refresh-mas-fx",
        "import-benchmark-total-returns",
        "portfolio",
        "daily-report",
        "holdings",
        "cash",
        "exposure",
        "reconciliation",
        "transactions",
        "performance",
        "backup-profile",
        "recipient-key-add",
        "recipient-key-revoke",
        "recipient-key-list",
        "report-export",
        "report-export-audit",
        "restore-profile",
        "rotate-key",
        "backtest-csv",
        "strategy-artifacts",
        "strategy-journal",
        "strategy-journal-list",
        "strategy-advisory-journal-open",
        "strategy-advisory-journal-dispose",
        "strategy-advisory-journal-link-evidence",
        "strategy-advisory-journal-list",
        "strategy-advisory-journal-configure",
        "strategy-advisory-journal-settings",
        "watchlist-add",
        "watchlist-configure",
        "watchlist-remove",
        "watchlist",
        "refresh-moomoo-prices",
        "refresh-moomoo-quotes",
        "schedule-render",
        "schedule-install",
        "schedule-status",
        "schedule-artifact",
        "notify-local",
        "notify-telegram",
        "telegram-recipient-add",
        "telegram-configure",
        "telegram-settings",
        "telegram-send",
        "telegram-delivery-audit",
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
        "drawdown-configure",
        "universe-configure",
        "universe-settings",
        "universe-evaluate",
        "benchmark-configure",
        "benchmark-settings",
        "benchmark-performance",
        "benchmark-templates",
        "benchmark-template-import",
        "benchmark-audit",
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
    result = runner.invoke(app, ["portfolio", "personal"])
    assert result.exit_code == 0, result.output
    assert "Portfolio: personal" in result.output
    assert "Events" in result.output
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


def test_cli_records_profile_scoped_advisory_journal_settings_and_disposition(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0

    opened = runner.invoke(app, ["strategy-advisory-journal-open", "personal", "advisory-1", "strategy:1"])

    assert opened.exit_code == 0, opened.output
    entry_id = json.loads(opened.output)["entry"]["entry_id"]
    disposed = runner.invoke(
        app,
        [
            "strategy-advisory-journal-dispose",
            "personal",
            entry_id,
            "accepted",
            "--reason",
            "manual review",
        ],
    )
    assert disposed.exit_code == 0, disposed.output
    assert "reason" not in json.loads(disposed.output)
    configured = runner.invoke(
        app,
        [
            "strategy-advisory-journal-configure",
            "personal",
            "--retention-days",
            "30",
            "--display-reasons",
        ],
    )
    assert configured.exit_code == 0, configured.output
    assert json.loads(configured.output)["configuration_version"] == 2
    listed = runner.invoke(app, ["strategy-advisory-journal-list", "personal"])

    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output)["entries"][0]["reason"] == "manual review"


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


def test_cli_configures_drawdown_without_execution(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0

    result = runner.invoke(
        app,
        [
            "drawdown-configure",
            "personal",
            "--warning-threshold",
            "0.30",
            "--response-policy",
            "record_only",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["drawdown"] == {
        "warning_threshold": "0.30",
        "response_policy": "record_only",
        "version": 2,
        "execution": "denied",
    }


def test_cli_configures_explicit_reference_benchmarks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0

    initial = runner.invoke(app, ["benchmark-settings", "personal"])
    assert initial.exit_code == 0, initial.output
    assert json.loads(initial.output)["components"] == [
        {
            "identifier": "US:SPX",
            "name": "S&P 500 Index",
            "currency": "USD",
            "weight": "0.75",
            "source_url": "https://www.spglobal.com/spdji/en/indices/equity/sp-500/",
            "return_basis": "total_return",
        },
        {
            "identifier": "SG:STI",
            "name": "Straits Times Index",
            "currency": "SGD",
            "weight": "0.25",
            "source_url": "https://www.lseg.com/content/dam/ftse-russell/en_us/documents/ground-rules/straits-times-index-ground-rules.pdf",
            "return_basis": "total_return",
        },
    ]
    result = runner.invoke(
        app,
        [
            "benchmark-configure",
            "personal",
            "--component",
            '{"identifier":"US:SPTR","name":"S&P 500 Total Return Index","currency":"USD","weight":"1","source_url":"https://www.spglobal.com/spdji/en/indices/equity/sp-500/"}',
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["configuration_version"] == 2
    assert json.loads(result.output)["reference_only"] is True
    assert runner.invoke(app, ["benchmark-configure", "personal"]).exit_code != 0


def test_cli_reports_weighted_total_return_benchmark_in_reporting_currency(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0
    returns = tmp_path / "returns.csv"
    returns.write_text(
        "date,identifier,currency,total_return_index,as_of_at,provider_id\n"
        "2026-01-02,US:SPX,USD,100,2026-01-02T12:00:00+00:00,spdj\n"
        "2026-01-03,US:SPX,USD,110,2026-01-03T12:00:00+00:00,spdj\n"
        "2026-01-02,SG:STI,SGD,100,2026-01-02T12:00:00+00:00,ftse\n"
        "2026-01-03,SG:STI,SGD,105,2026-01-03T12:00:00+00:00,ftse\n"
    )
    fx = tmp_path / "fx.csv"
    fx.write_text(
        "date,base_currency,quote_currency,rate,as_of_at,provider_id\n"
        "2026-01-02,USD,SGD,1.35,2026-01-02T12:00:00+00:00,mas\n"
        "2026-01-03,USD,SGD,1.40,2026-01-03T12:00:00+00:00,mas\n"
    )
    assert runner.invoke(app, ["import-benchmark-total-returns", "personal", str(returns)]).exit_code == 0
    assert runner.invoke(app, ["import-fx", "personal", str(fx)]).exit_code == 0

    result = runner.invoke(
        app,
        [
            "benchmark-performance",
            "personal",
            "--start-date",
            "2026-01-02",
            "--end-date",
            "2026-01-03",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "available"
    assert payload["reporting_currency"] == "SGD"
    assert payload["components"][0]["reporting_return"] == str(
        Decimal("110") * Decimal("1.4") / Decimal("135") - Decimal("1")
    )
    assert payload["aggregate_return"] == str(
        Decimal("0.75") * (Decimal("110") * Decimal("1.4") / Decimal("135") - Decimal("1"))
        + Decimal("0.25") * Decimal("0.05")
    )
    assert payload["execution"] == "denied"


def test_cli_exports_portfolio_only_to_explicit_recipient(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    key = tmp_path / "key"
    recipient = X25519PrivateKey.generate()
    public_key = b64encode(recipient.public_key().public_bytes_raw()).decode()
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0
    assert runner.invoke(app, ["recipient-key-add", "analyst", public_key]).exit_code == 0

    destination = tmp_path / "portfolio.stonks"
    result = runner.invoke(
        app,
        ["report-export", "personal", str(destination), "--recipient", "analyst"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["integrity"] == "authenticated"
    assert destination.is_file()
    assert b"portfolio-report" not in destination.read_bytes()


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


def test_cli_reports_usd_nav_with_explicit_base_currency(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0
    events = tmp_path / "events.csv"
    events.write_text(
        "account_id,occurred_at,kind,currency,amount,quantity,symbol,market,instrument_currency\n"
        "main,2026-01-01T00:00:00+00:00,cash_deposit,USD,100,,,,\n"
        "main,2026-01-02T00:00:00+00:00,buy,USD,50,1,SPY,US,USD\n"
    )
    prices = tmp_path / "prices.csv"
    prices.write_text("date,symbol,market,currency,close\n2026-01-02,SPY,US,USD,50\n")
    assert runner.invoke(app, ["import-csv", "personal", str(events)]).exit_code == 0
    assert runner.invoke(app, ["import-prices", "personal", str(prices)]).exit_code == 0

    result = runner.invoke(app, ["portfolio", "personal", "--base-currency", "USD", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["nav"] == {
        "currency": "USD",
        "cash": "50",
        "market_value": "50",
        "total": "100",
    }


def test_cli_refreshes_mas_fx_with_explicit_date_range(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0
    calls = []

    def refresh(ledger, start_date: date, end_date: date) -> FxReferenceRefresh:
        calls.append((ledger.config.name, start_date, end_date))
        return FxReferenceRefresh(
            "mas",
            "https://eservices.mas.gov.sg/statistics/msb/exchangerates.aspx",
            start_date,
            end_date,
            "a" * 64,
            2,
            1,
        )

    monkeypatch.setattr(cli, "refresh_mas_usd_sgd_reference_rates", refresh)

    result = runner.invoke(app, ["refresh-mas-fx", "personal", "2026-07-01", "2026-07-02"])

    assert result.exit_code == 0, result.output
    assert calls == [("personal", date(2026, 7, 1), date(2026, 7, 2))]
    assert json.loads(result.output) == {
        "profile": "personal",
        "provider_id": "mas",
        "source_url": "https://eservices.mas.gov.sg/statistics/msb/exchangerates.aspx",
        "start_date": "2026-07-01",
        "end_date": "2026-07-02",
        "source_hash": "a" * 64,
        "fetched_rates": 2,
        "persisted_rates": 1,
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


def test_cli_delivers_telegram_only_after_profile_configuration(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("STONKS_CLI_TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("STONKS_CLI_TELEGRAM_RECIPIENT", "recipient")
    monkeypatch.setattr(telegram_delivery.platform, "system", lambda: "Linux")
    monkeypatch.setattr(telegram_delivery, "notify_telegram", lambda token, chat_id, title, message: True)
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0
    assert runner.invoke(app, ["telegram-recipient-add", "personal", "primary"]).exit_code == 0
    assert runner.invoke(app, ["telegram-configure", "personal", "--recipient", "primary"]).exit_code == 0

    result = runner.invoke(
        app,
        [
            "notify-telegram",
            "personal",
            "advisory-1",
            "--event-category",
            "advisory",
            "--instrument",
            "US:SPY",
            "--action",
            "buy",
            "--rationale",
            "trend",
        ],
    )

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


def test_monitor_refreshes_without_environment_telegram_delivery(tmp_path: Path, monkeypatch) -> None:
    class Provider:
        def daily_prices(self, instruments, start, end):
            return (
                DailyPrice(instruments[0], start, "100", "a" * 64),
                DailyPrice(instruments[0], end, "106", "a" * 64),
            )

    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cli.MoomooReadOnlyProvider, "from_installed_sdk", lambda endpoint: Provider())
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0
    assert runner.invoke(app, ["watchlist-add", "personal", "SPY", "US", "USD"]).exit_code == 0

    result = runner.invoke(app, ["monitor", "personal", "--days", "2"])

    assert result.exit_code == 0, result.output
    artifact = latest_scheduled_artifact(
        EncryptedLedger(load_profile("personal")), "com.stonks-cli.personal"
    )
    assert artifact is not None
    assert artifact.status == "succeeded"
    assert result.output == f"{artifact.artifact.content}\n"
    payload = json.loads(result.output)
    assert payload["alerts"][0]["instrument"] == "US:SPY"
    assert payload["telegram_delivered"] is False


def test_schedule_artifact_renders_persisted_content_and_status(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        cli,
        "macos_schedule_status",
        lambda definition: ScheduleStatus(definition.label, True, False),
    )
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0
    ledger = EncryptedLedger(load_profile("personal"))
    persisted = cli.create_artifact("report", '{"profile":"personal"}')
    cli.persist_scheduled_artifact(ledger, "com.stonks-cli.personal", persisted, "succeeded")

    artifact_result = runner.invoke(app, ["schedule-artifact", "personal"])
    status_result = runner.invoke(app, ["schedule-status", "personal"])

    assert artifact_result.exit_code == 0, artifact_result.output
    assert artifact_result.output == '{"profile":"personal"}\n'
    assert status_result.exit_code == 0, status_result.output
    assert json.loads(status_result.output)["last_artifact"] == {
        "artifact_id": persisted.artifact_id,
        "status": "succeeded",
        "created_at": persisted.created_at.isoformat(),
    }


def test_monitor_persists_failed_scheduled_artifact(tmp_path: Path, monkeypatch) -> None:
    class Provider:
        def daily_prices(self, instruments, start, end):
            raise RuntimeError("unavailable")

    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cli.MoomooReadOnlyProvider, "from_installed_sdk", lambda endpoint: Provider())
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0
    assert runner.invoke(app, ["watchlist-add", "personal", "SPY", "US", "USD"]).exit_code == 0

    result = runner.invoke(app, ["monitor", "personal", "--days", "2"])

    assert result.exit_code != 0
    artifact = latest_scheduled_artifact(
        EncryptedLedger(load_profile("personal")), "com.stonks-cli.personal"
    )
    assert artifact is not None
    assert artifact.status == "failed"
    assert "RuntimeError" in artifact.artifact.content


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
