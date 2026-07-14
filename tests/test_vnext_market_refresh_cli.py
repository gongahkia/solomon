from __future__ import annotations

import json

from typer.testing import CliRunner

import stonks_cli.cli as cli
from stonks_cli.cli import app
from stonks_cli.errors import ExitCodes
from stonks_cli.vnext.errors import VNextExternalDataError
from stonks_cli.vnext.moomoo import MoomooUSQuote


def test_vnext_market_refresh_cli_emits_read_only_preentitled_quotes(monkeypatch):
    quote = MoomooUSQuote("US.AAPL", "2026-01-01", "09:30:00", 200.0, 198.0, 201.0, 197.0, 199.0, 2000.0, 400000.0, False)
    monkeypatch.setattr(cli, "refresh_moomoo_market_data", lambda config, symbols: (quote,))

    result = CliRunner().invoke(app, ["refresh-market", "--symbol", "US.AAPL"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["read_only"] is True
    assert payload["quotes"] == [
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


def test_vnext_market_refresh_cli_fails_closed_for_external_data(monkeypatch):
    def fail(config: object, symbols: list[str]) -> tuple[()]:
        raise VNextExternalDataError("Moomoo US quotes are malformed")

    monkeypatch.setattr(cli, "refresh_moomoo_market_data", fail)

    result = CliRunner().invoke(app, ["refresh-market", "--symbol", "US.AAPL"])

    assert result.exit_code == ExitCodes.PROVIDER_ERROR
    assert "Moomoo US quotes are malformed" in result.output
