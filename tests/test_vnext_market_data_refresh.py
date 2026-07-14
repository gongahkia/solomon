from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import stonks_cli.cli as cli
from stonks_cli.cli import app
from stonks_cli.config import AppConfig
from stonks_cli.errors import ExitCodes
from stonks_cli.vnext.errors import OpenDDataEntitlementMissingError, VNextExternalDataError
from stonks_cli.vnext.market_data_refresh import refresh_moomoo_market_data
from stonks_cli.vnext.moomoo import MoomooSdkCompatibility, MoomooSdkStatus, MoomooUSQuote


def test_broker_market_data_refresh_cli_emits_preentitled_quotes(monkeypatch):
    quote = MoomooUSQuote("US.AAPL", "2026-01-01", "09:30:00", 200.0, 198.0, 201.0, 197.0, 199.0, 2000.0, 400000.0, False)
    monkeypatch.setattr(cli, "refresh_moomoo_market_data", lambda config, symbols: (quote,))

    result = CliRunner().invoke(app, ["broker", "market-data-refresh", "--symbol", "US.AAPL"])

    assert result.exit_code == 0
    assert json.loads(result.output)["quotes"] == [
        {
            "symbol": "US.AAPL",
            "quoted_date": "2026-01-01",
            "quoted_time": "09:30:00",
            "last_price": 200.0,
            "open_price": 198.0,
            "high_price": 201.0,
            "low_price": 197.0,
            "previous_close_price": 199.0,
            "volume": 2000.0,
            "turnover": 400000.0,
            "suspended": False,
        }
    ]


def test_broker_market_data_refresh_cli_fails_closed_for_external_data(monkeypatch):
    def fail(config: AppConfig, symbols: list[str]) -> tuple[MoomooUSQuote, ...]:
        raise VNextExternalDataError("Moomoo US quotes are malformed")

    monkeypatch.setattr(cli, "refresh_moomoo_market_data", fail)

    result = CliRunner().invoke(app, ["broker", "market-data-refresh", "--symbol", "US.AAPL"])

    assert result.exit_code == ExitCodes.PROVIDER_ERROR
    assert "Moomoo US quotes are malformed" in result.output


def test_refresh_moomoo_market_data_requires_observed_entitlements_before_quote_reads():
    config = AppConfig.model_validate(
        {"vnext": {"enabled": True, "moomoo": {"enabled": True}, "features": {"broker_data": True}}}
    )

    def compatible() -> MoomooSdkCompatibility:
        return MoomooSdkCompatibility(MoomooSdkStatus.COMPATIBLE, "sdk_compatible", "9.1.0")

    class Context:
        quote_read = False

        def query_subscription(self, **kwargs):
            return 0, {
                "total_used": 1,
                "own_used": 1,
                "remain": 999,
                "own_security_firm": "Moomoo SG",
                "sub_list": {"QUOTE": ["US.AAPL"]},
            }

        def get_stock_quote(self, symbols):
            self.quote_read = True
            return 0, [
                {
                    "code": "US.AAPL",
                    "data_date": "2026-01-01",
                    "data_time": "09:30:00",
                    "last_price": 200,
                    "open_price": 198,
                    "high_price": 201,
                    "low_price": 197,
                    "prev_close_price": 199,
                    "volume": 2000,
                    "turnover": 400000,
                    "suspension": False,
                }
            ]

        def close(self) -> None:
            return None

    context = Context()
    assert refresh_moomoo_market_data(
        config,
        ("US.AAPL",),
        sdk_compatibility=compatible,
        context_factory=lambda host, port: context,
    ) == (MoomooUSQuote("US.AAPL", "2026-01-01", "09:30:00", 200.0, 198.0, 201.0, 197.0, 199.0, 2000.0, 400000.0, False),)
    assert context.quote_read is True
    context.quote_read = False
    with pytest.raises(OpenDDataEntitlementMissingError):
        refresh_moomoo_market_data(
            config,
            ("US.MSFT",),
            sdk_compatibility=compatible,
            context_factory=lambda host, port: context,
        )
    assert context.quote_read is False
