from typer.testing import CliRunner

from stonks_cli.cli import app


def test_vnext_cli_root_renders_help_without_broker_submission_command():
    result = CliRunner().invoke(app, ["vnext"])

    assert result.exit_code == 0
    assert "vNext decision-support commands; broker order submission is unavailable." in result.output
    assert "crypto-universe" in result.output
    assert "order-submit" not in result.output


def test_vnext_cli_root_help_is_available():
    result = CliRunner().invoke(app, ["vnext", "--help"])

    assert result.exit_code == 0
    assert "vNext decision-support commands; broker order submission is unavailable." in result.output
