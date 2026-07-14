import pytest

from stonks_cli.vnext.telegram_report_template import render_telegram_report_template


def test_telegram_report_template_wraps_valid_daily_report_without_delivery_behavior():
    rendered = render_telegram_report_template("DAILY REPORT\nPORTFOLIO RISK REPORT\ngross_leverage: 1.000000")

    assert rendered == "STONKS vNEXT DAILY REPORT\n\nDAILY REPORT\nPORTFOLIO RISK REPORT\ngross_leverage: 1.000000"


def test_telegram_report_template_fails_closed_for_missing_or_malformed_daily_report():
    with pytest.raises(ValueError, match="requires a daily report"):
        render_telegram_report_template("PORTFOLIO RISK REPORT")
    with pytest.raises(ValueError, match="requires a daily report"):
        render_telegram_report_template(None)
