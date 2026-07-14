from __future__ import annotations


def render_telegram_report_template(daily_report: str) -> str:
    if not isinstance(daily_report, str) or not daily_report.startswith("DAILY REPORT\n"):
        raise ValueError("Telegram report requires a daily report")
    if not daily_report.strip():
        raise ValueError("Telegram report is empty")
    return f"STONKS vNEXT DAILY REPORT\n\n{daily_report}"
