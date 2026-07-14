import json

from typer.testing import CliRunner

from stonks_cli.cli import app
from stonks_cli.errors import ExitCodes


def _snapshot() -> dict[str, object]:
    return {
        "provider_id": "moomoo",
        "account_id": "100",
        "captured_at": "2026-07-14T12:00:00Z",
        "holdings": [
            {"holding_id": "aapl", "symbol": "US.AAPL", "asset_class": "equity", "quantity": 2.0, "currency": "USD", "market_value": 400.0}
        ],
    }


def test_vnext_portfolio_show_cli_renders_canonical_read_only_snapshot(tmp_path):
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps(_snapshot()), encoding="utf-8")

    result = CliRunner().invoke(app, ["show-portfolio", "--snapshot", str(path)])

    assert result.exit_code == 0
    assert json.loads(result.output) == _snapshot()


def test_vnext_portfolio_show_cli_fails_closed_for_malformed_snapshot(tmp_path):
    path = tmp_path / "portfolio.json"
    path.write_text("{}", encoding="utf-8")

    result = CliRunner().invoke(app, ["show-portfolio", "--snapshot", str(path)])

    assert result.exit_code == ExitCodes.USAGE_ERROR
    assert "snapshot fields are invalid" in result.output
