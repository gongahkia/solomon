from typer.testing import CliRunner

from stonks_cli.cli import app


def test_root_help_exposes_flat_decision_support_commands():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "universe-crypto" in result.output
    assert "ticket-order" in result.output
    assert "order-submit" not in result.output
