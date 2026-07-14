import json
from datetime import UTC, datetime

from typer.testing import CliRunner

import stonks_cli.cli as cli
from stonks_cli.cli import app
from stonks_cli.config import AppConfig
from stonks_cli.errors import ExitCodes
from stonks_cli.vnext.portfolio_domain import PortfolioAssetClass, PortfolioHolding, PortfolioSnapshot


def _config() -> AppConfig:
    return AppConfig.model_validate(
        {"vnext": {"enabled": True, "moomoo": {"enabled": True}, "features": {"broker_data": True, "portfolio": True}}}
    )


def test_vnext_portfolio_import_cli_emits_canonical_read_only_holdings(monkeypatch):
    captured_at = datetime(2026, 7, 14, 12, tzinfo=UTC)
    snapshot = PortfolioSnapshot(
        "moomoo", "100", captured_at, (PortfolioHolding("100", "aapl", "US.AAPL", PortfolioAssetClass.EQUITY, 2.0, "USD", 400.0),)
    )
    monkeypatch.setattr(cli, "load_config", _config)
    monkeypatch.setattr(cli, "import_moomoo_holdings", lambda config, account, captured: snapshot)

    result = CliRunner().invoke(
        app,
        ["import-portfolio", "--account-id", "100", "--account-index", "0", "--trading-environment", "REAL", "--captured-at", "2026-07-14T12:00:00Z"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["holdings"] == [
        {"asset_class": "equity", "currency": "USD", "holding_id": "aapl", "market_value": 400.0, "quantity": 2.0, "symbol": "US.AAPL"}
    ]


def test_vnext_portfolio_import_cli_fails_closed_for_malformed_capture_time():
    result = CliRunner().invoke(
        app,
        ["import-portfolio", "--account-id", "100", "--account-index", "0", "--trading-environment", "REAL", "--captured-at", "bad-time"],
    )

    assert result.exit_code == ExitCodes.USAGE_ERROR
    assert "Invalid isoformat" in result.output
