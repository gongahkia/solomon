from __future__ import annotations

import json
from datetime import date, timedelta

from stonks_cli.commands import do_earnings
from stonks_cli.data.earnings import EarningsEvent


def test_do_earnings_calendar_mode_uses_configured_tickers(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "tickers": ["AAPL", "MSFT.US"],
                "watchlists": {"growth": ["NVDA.US", "AAPL.US"]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    today = date.today()
    calls: list[str] = []

    def _fake_fetch(ticker: str, quarters: int = 8) -> list[EarningsEvent]:
        calls.append(ticker)
        if ticker == "AAPL":
            return [
                EarningsEvent(
                    ticker="AAPL",
                    company_name="Apple Inc.",
                    report_date=today + timedelta(days=3),
                    report_time="after_market",
                    eps_estimate=1.2,
                )
            ]
        if ticker == "NVDA":
            return [
                EarningsEvent(
                    ticker="NVDA",
                    company_name="NVIDIA Corp.",
                    report_date=today + timedelta(days=1),
                    report_time="after_market",
                    eps_estimate=2.1,
                )
            ]
        return []

    monkeypatch.setattr("stonks_cli.data.earnings.fetch_ticker_earnings_history", _fake_fetch)

    out = do_earnings()
    assert out["mode"] == "calendar"
    assert out["tickers_scanned"] == 3
    assert [e["ticker"] for e in out["events"]] == ["NVDA", "AAPL"]
    assert set(calls) == {"AAPL", "MSFT", "NVDA"}


def test_do_earnings_calendar_mode_supports_show_next(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"tickers": ["AAPL"]}), encoding="utf-8")
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    today = date.today()

    def _fake_fetch(ticker: str, quarters: int = 8) -> list[EarningsEvent]:
        return [
            EarningsEvent(
                ticker="AAPL",
                company_name="Apple Inc.",
                report_date=today + timedelta(days=2),
                report_time="after_market",
                eps_estimate=1.0,
            )
        ]

    monkeypatch.setattr("stonks_cli.data.earnings.fetch_ticker_earnings_history", _fake_fetch)

    out = do_earnings(show_next=True)
    assert out["mode"] == "next"
    assert out["ticker"] == "AAPL"
    assert out["days_until"] == 2
    assert out["next_earnings"]["ticker"] == "AAPL"
