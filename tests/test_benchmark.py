from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from stonks_cli.benchmark import (
    BenchmarkTotalReturnPoint,
    calculate_period_report,
    import_total_return_csv,
    latest_total_return_points,
)
from stonks_cli.config import BenchmarkComponent, BenchmarkSettings, ProfileConfig
from stonks_cli.market_data import FxRate, fx_rates_for_session, import_fx_rates_csv
from stonks_cli.storage import EncryptedLedger, generate_key_file
from stonks_cli.types import Currency


def test_total_return_period_uses_explicit_fx_and_fails_closed_when_input_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    key = tmp_path / "key"
    generate_key_file(key)
    component = BenchmarkComponent(
        "US:SPX",
        "S&P 500 Index",
        Currency.USD,
        "1",
        "https://www.spglobal.com/spdji/en/indices/equity/sp-500/",
    )
    settings = BenchmarkSettings((component,), 3)
    start_date = date(2026, 1, 2)
    end_date = date(2026, 1, 3)
    points = {
        ("US:SPX", start_date): BenchmarkTotalReturnPoint(
            "US:SPX", Currency.USD, start_date, Decimal("100"), "a" * 64
        ),
        ("US:SPX", end_date): BenchmarkTotalReturnPoint(
            "US:SPX", Currency.USD, end_date, Decimal("110"), "b" * 64
        ),
    }
    start_fx = FxRate(Currency.USD, Currency.SGD, start_date, "1.35", "c" * 64)
    end_fx = FxRate(Currency.USD, Currency.SGD, end_date, "1.40", "d" * 64)

    report = calculate_period_report(
        settings,
        points,
        start_date=start_date,
        end_date=end_date,
        reporting_currency=Currency.SGD,
        start_fx_rates={(Currency.USD, Currency.SGD): start_fx},
        end_fx_rates={(Currency.USD, Currency.SGD): end_fx},
    )

    assert report.status == "available"
    assert report.components[0].native_return == Decimal("0.1")
    assert report.components[0].reporting_return == Decimal("110") * Decimal("1.4") / Decimal(
        "135"
    ) - Decimal("1")
    assert report.aggregate_return == report.components[0].reporting_return
    missing = calculate_period_report(
        settings,
        {},
        start_date=start_date,
        end_date=end_date,
        reporting_currency=Currency.SGD,
        start_fx_rates={(Currency.USD, Currency.SGD): start_fx},
        end_fx_rates={(Currency.USD, Currency.SGD): end_fx},
    )
    assert missing.status == "unavailable"
    assert missing.aggregate_return is None
    assert missing.components[0].reason == "missing start total-return index level"
    stale = calculate_period_report(
        settings,
        {("US:SPX", start_date): points[("US:SPX", start_date)]},
        start_date=start_date,
        end_date=end_date,
        reporting_currency=Currency.SGD,
        start_fx_rates={(Currency.USD, Currency.SGD): start_fx},
        end_fx_rates={(Currency.USD, Currency.SGD): end_fx},
    )
    assert stale.status == "stale"
    assert stale.components[0].reason == "end total-return index level is stale"


def test_total_return_import_persists_encrypted_source_and_latest_revision(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    key = tmp_path / "key"
    generate_key_file(key)
    ledger = EncryptedLedger(ProfileConfig("personal", str(key)))
    source = tmp_path / "benchmark.csv"
    source.write_text(
        "date,identifier,currency,total_return_index,as_of_at,provider_id\n"
        "2026-01-02,US:SPX,USD,100,2026-01-02T12:00:00+00:00,spdj\n"
    )

    assert import_total_return_csv(ledger, source) == 1
    points = latest_total_return_points(ledger)

    point = points[("US:SPX", date(2026, 1, 2))]
    assert point.index_level == Decimal("100")
    assert point.as_of_at == datetime(2026, 1, 2, 12, tzinfo=UTC)
    assert point.provider_id == "spdj"
    assert b"total_return_index" not in ledger.path.read_bytes()


def test_fx_rates_for_session_selects_latest_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    key = tmp_path / "key"
    generate_key_file(key)
    ledger = EncryptedLedger(ProfileConfig("personal", str(key)))
    source = tmp_path / "fx.csv"
    source.write_text(
        "date,base_currency,quote_currency,rate,as_of_at,provider_id\n"
        "2026-01-02,USD,SGD,1.35,2026-01-02T10:00:00+00:00,mas\n"
    )
    assert import_fx_rates_csv(ledger, source) == 1
    source.write_text(
        "date,base_currency,quote_currency,rate,as_of_at,provider_id\n"
        "2026-01-02,USD,SGD,1.36,2026-01-02T12:00:00+00:00,mas\n"
    )
    assert import_fx_rates_csv(ledger, source) == 1
    rate = fx_rates_for_session(ledger, date(2026, 1, 2))[(Currency.USD, Currency.SGD)]
    assert rate.rate == Decimal("1.36")
    assert rate.provider_id == "mas"
