from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from conftest import encrypted_ledger

from stonks_cli.market_data import (
    DailyPrice,
    FxRate,
    QuoteQuality,
    QuoteSnapshot,
    archive_and_store_daily_prices,
    archive_and_store_quote_snapshots,
    convert_currency,
    historical_prices,
    import_daily_prices_csv,
    import_fx_rates_csv,
    latest_fx_rates,
    latest_prices,
    latest_quote_snapshots,
    price_freshness,
    price_revisions,
)
from stonks_cli.types import Currency, Instrument


def test_price_import_keeps_latest_value(tmp_path: Path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    source = tmp_path / "prices.csv"
    source.write_text(
        "date,symbol,market,currency,close\n2026-01-01,SPY,US,USD,100\n2026-01-02,SPY,US,USD,101\n"
    )
    assert import_daily_prices_csv(ledger, source) == 2
    assert str(latest_prices(ledger)["US:SPY"]) == "101"
    assert historical_prices(ledger, "US:SPY") == (
        (date(2026, 1, 1), Decimal("100")),
        (date(2026, 1, 2), Decimal("101")),
    )


def test_market_refresh_archives_normalized_source(tmp_path: Path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    price = DailyPrice(Instrument("SPY", "US", Currency.USD), date(2026, 1, 1), Decimal("100"), "a" * 64)

    count, source_hash = archive_and_store_daily_prices(ledger, (price,))

    assert count == 1
    assert (ledger.sources / f"{source_hash}.enc").is_file()


def test_market_data_tracks_revisions_freshness_and_quote_quality(tmp_path: Path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    instrument = Instrument("SPY", "US", Currency.USD)
    first = DailyPrice(instrument, date(2026, 1, 1), Decimal("100"), "a" * 64)
    second = DailyPrice(instrument, date(2026, 1, 1), Decimal("101"), "b" * 64)

    assert archive_and_store_daily_prices(ledger, (first,))[0] == 1
    assert archive_and_store_daily_prices(ledger, (second,))[0] == 1
    assert {item.close for item in price_revisions(ledger, instrument.key)} == {
        Decimal("100"),
        Decimal("101"),
    }
    freshness = price_freshness(
        ledger, instrument.key, as_of=date(2026, 1, 4), maximum_age_days=2
    )
    assert freshness.age == timedelta(days=3)
    assert freshness.stale is True
    quote = QuoteSnapshot(
        instrument,
        Decimal("102"),
        datetime(2026, 1, 4, tzinfo=UTC),
        QuoteQuality.UNKNOWN,
        "c" * 64,
        "2026-01-03 16:00:00",
    )
    count, source_hash = archive_and_store_quote_snapshots(ledger, (quote,))

    assert count == 1
    assert latest_quote_snapshots(ledger)[instrument.key].quality is QuoteQuality.UNKNOWN
    assert (ledger.sources / f"{source_hash}.enc").is_file()


def test_fx_import_requires_provenance_and_supports_direct_or_inverse_rates(tmp_path: Path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    source = tmp_path / "fx.csv"
    source.write_text("date,base_currency,quote_currency,rate\n2026-01-02,USD,SGD,1.35\n")

    assert import_fx_rates_csv(ledger, source) == 1
    rates = latest_fx_rates(ledger)
    assert convert_currency(Decimal("10"), Currency.USD, Currency.SGD, rates) == Decimal("13.50")
    assert convert_currency(Decimal("13.5"), Currency.SGD, Currency.USD, rates) == Decimal("10")
    assert FxRate(Currency.USD, Currency.SGD, date(2026, 1, 2), "1.35", "a" * 64).rate == Decimal(
        "1.35"
    )
