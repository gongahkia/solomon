import json

from typer.testing import CliRunner

import stonks_cli.cli as cli
from stonks_cli.cli import app
from stonks_cli.config import AppConfig
from stonks_cli.vnext.telegram_client import send_telegram_message
from stonks_cli.vnext.telegram_configuration import TelegramDeliveryConfiguration
from stonks_cli.vnext.telegram_report_template import render_telegram_report_template


def test_daily_workflow_renders_validated_report_then_delivers_the_same_manual_message(tmp_path, monkeypatch):
    path = tmp_path / "daily-report.json"
    path.write_text(
        json.dumps(
            {
                "exposure": {"account_id": "100", "quote_currency": "USD", "long_exposure": 750.0, "short_exposure": 250.0, "gross_exposure": 1000.0, "net_exposure": 500.0},
                "nav": {"account_id": "100", "currency": "USD", "captured_at": "2026-07-14T12:00:00Z", "holdings_value": 1000.0, "cash_value": 0.0, "net_asset_value": 1000.0},
                "data_confidence": {"provider_id": "fixture", "evaluated_at": "2026-07-14T12:00:00Z", "maximum_age_seconds": 600.0, "source_count": 2, "fresh_source_count": 1, "stale_source_urls": ["https://example.test/stale"], "score": 0.5},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig.model_validate({"vnext": {"enabled": True, "features": {"operator_reports": True}}}))

    report = CliRunner().invoke(app, ["report-daily", "--input", str(path)])

    calls = []
    message = render_telegram_report_template(report.output)
    receipt = send_telegram_message(
        TelegramDeliveryConfiguration("123456:ABC_def", "-100123"),
        message,
        post=lambda *args, **kwargs: calls.append((args, kwargs)) or _Response(),
    )
    assert report.exit_code == 0
    assert message == f"STONKS vNEXT DAILY REPORT\n\n{report.output}"
    assert receipt.message_id == 1
    assert calls[0][1]["json_data"] == {"chat_id": "-100123", "text": message}


class _Response:
    status_code = 200

    def json(self):
        return {"ok": True, "result": {"message_id": 1}}
