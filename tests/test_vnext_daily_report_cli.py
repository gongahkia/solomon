import json

from typer.testing import CliRunner

import stonks_cli.cli as cli
from stonks_cli.cli import app
from stonks_cli.config import AppConfig
from stonks_cli.errors import ExitCodes


def _enabled_config() -> AppConfig:
    return AppConfig.model_validate({"vnext": {"enabled": True, "features": {"operator_reports": True}}})


def _input() -> dict[str, object]:
    return {
        "exposure": {"account_id": "100", "quote_currency": "USD", "long_exposure": 750.0, "short_exposure": 250.0, "gross_exposure": 1000.0, "net_exposure": 500.0},
        "nav": {"account_id": "100", "currency": "USD", "captured_at": "2026-07-14T12:00:00Z", "holdings_value": 1000.0, "cash_value": 0.0, "net_asset_value": 1000.0},
        "data_confidence": {"provider_id": "fixture", "evaluated_at": "2026-07-14T12:00:00Z", "maximum_age_seconds": 600.0, "source_count": 2, "fresh_source_count": 1, "stale_source_urls": ["https://example.test/stale"], "score": 0.5},
    }


def test_vnext_daily_report_cli_renders_validated_portfolio_risk_report(tmp_path, monkeypatch):
    path = tmp_path / "daily-report.json"
    path.write_text(json.dumps(_input()), encoding="utf-8")
    monkeypatch.setattr(cli, "load_config", _enabled_config)

    result = CliRunner().invoke(app, ["report-daily", "--input", str(path)])

    assert result.exit_code == 0
    assert result.output.startswith("DAILY REPORT\nPORTFOLIO RISK REPORT\n")
    assert "gross_leverage: 1.000000" in result.output


def test_vnext_daily_report_cli_fails_closed_for_disabled_or_malformed_input(tmp_path, monkeypatch):
    path = tmp_path / "daily-report.json"
    path.write_text("{}", encoding="utf-8")

    result = CliRunner().invoke(app, ["report-daily", "--input", str(path)])

    assert result.exit_code == ExitCodes.BAD_CONFIG
    monkeypatch.setattr(cli, "load_config", _enabled_config)
    result = CliRunner().invoke(app, ["report-daily", "--input", str(path)])
    assert result.exit_code == ExitCodes.USAGE_ERROR
    assert "input fields are invalid" in result.output
