from typer.testing import CliRunner

from stonks_cli.cli import app
from stonks_cli.errors import ExitCodes


def _arguments() -> list[str]:
    return [
        "vnext",
        "order-ticket",
        "--ticket-id",
        "ticket-1",
        "--account-id",
        "100",
        "--symbol",
        "US.AAPL",
        "--side",
        "buy",
        "--quantity",
        "2.0",
        "--limit-price",
        "200.0",
        "--currency",
        "USD",
        "--rationale",
        "rebalance to approved target weight",
        "--prepared-at",
        "2026-07-14T12:00:00Z",
        "--reviewed-by",
        "operator@example.test",
        "--reviewed-at",
        "2026-07-14T12:01:00Z",
    ]


def test_vnext_order_ticket_cli_renders_manual_reviewed_ticket_without_submission():
    result = CliRunner().invoke(app, _arguments())

    assert result.exit_code == 0
    assert "MANUAL BROKER-APP ORDER TICKET" in result.output
    assert "submission: manual broker-app entry only; no API call made" in result.output


def test_vnext_order_ticket_cli_fails_closed_for_invalid_review_chronology():
    arguments = _arguments()
    arguments[-1] = "2026-07-14T11:59:59Z"

    result = CliRunner().invoke(app, arguments)

    assert result.exit_code == ExitCodes.USAGE_ERROR
    assert "review precedes preparation" in result.output
