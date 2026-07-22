from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import encrypted_ledger

from stonks_cli.errors import ProviderError
from stonks_cli.market_data import (
    DailyPrice,
    FxRate,
    MarketSession,
    QuoteQuality,
    QuoteSnapshot,
    QuoteStatus,
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
from stonks_cli.storage import decrypt
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


def test_daily_prices_require_complete_ordered_ohlc_and_preserve_it(tmp_path: Path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    instrument = Instrument("SPY", "US", Currency.USD)
    price = DailyPrice(
        instrument,
        date(2026, 1, 1),
        "100",
        "a" * 64,
        open="99",
        high="102",
        low="98",
    )

    assert archive_and_store_daily_prices(ledger, (price,))[0] == 1
    revision = price_revisions(ledger, instrument.key)[0]
    assert (revision.open, revision.high, revision.low, revision.close) == (
        Decimal("99"),
        Decimal("102"),
        Decimal("98"),
        Decimal("100"),
    )
    with pytest.raises(ValueError, match="complete"):
        DailyPrice(instrument, date(2026, 1, 2), "100", "b" * 64, open="99")
    with pytest.raises(ValueError, match="ordering"):
        DailyPrice(
            instrument,
            date(2026, 1, 2),
            "100",
            "b" * 64,
            open="99",
            high="99",
            low="98",
        )


def test_price_csv_accepts_complete_ohlc_and_rejects_partial_columns(tmp_path: Path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    complete = tmp_path / "complete.csv"
    complete.write_text(
        "date,symbol,market,currency,open,high,low,close\n"
        "2026-01-01,SPY,US,USD,99,102,98,100\n"
    )
    partial = tmp_path / "partial.csv"
    partial.write_text("date,symbol,market,currency,open,close\n2026-01-02,SPY,US,USD,100,101\n")

    assert import_daily_prices_csv(ledger, complete) == 1
    assert price_revisions(ledger, "US:SPY")[0].has_complete_ohlc is True
    with pytest.raises(ProviderError, match="OHLC"):
        import_daily_prices_csv(ledger, partial)


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
        QuoteQuality.REAL_TIME,
        "c" * 64,
        "2026-01-03 16:00:00",
        QuoteStatus.AVAILABLE,
        datetime(2026, 1, 3, 16, tzinfo=UTC),
        Decimal("101"),
        Decimal("103"),
        Decimal("102"),
        Decimal("2"),
        datetime(2026, 1, 3, 16, tzinfo=UTC),
        "snapshot",
        MarketSession.REGULAR,
        raw_payload={"provider": "opend", "raw_price": "102"},
    )
    count, source_hash = archive_and_store_quote_snapshots(ledger, (quote,))

    assert count == 1
    snapshot = latest_quote_snapshots(ledger)[instrument.key]
    assert snapshot.current_price == Decimal("102")
    assert snapshot.provider_fingerprint == "c" * 64
    assert (ledger.sources / f"{source_hash}.enc").is_file()
    raw = decrypt(
        ledger.key,
        (ledger.sources / f"{source_hash}.enc").read_bytes(),
        profile=ledger.config.name,
        label=f"source:{source_hash}",
    )
    assert raw == b'[{"provider":"opend","raw_price":"102"}]'


def test_quote_snapshot_storage_migrates_legacy_rows(tmp_path: Path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    with ledger.connection() as connection:
        connection.execute(
            """
            CREATE TABLE quote_snapshots (
                instrument_key TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                last_price TEXT NOT NULL,
                currency TEXT NOT NULL,
                quality TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                vendor_time TEXT,
                PRIMARY KEY(instrument_key, observed_at, source_hash)
            )
            """
        )
        connection.execute(
            "INSERT INTO quote_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("US:SPY", "2026-01-02T15:00:00+00:00", "100", "USD", "unknown", "d" * 64, None),
        )

    snapshot = latest_quote_snapshots(ledger)["US:SPY"]

    assert snapshot.status is QuoteStatus.UNKNOWN
    assert snapshot.last_price == Decimal("100")
    assert snapshot.current_price is None


def test_quote_snapshot_storage_normalizes_preexisting_market_session(tmp_path: Path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    with ledger.connection() as connection:
        connection.execute(
            """
            CREATE TABLE quote_snapshots (
                instrument_key TEXT NOT NULL, observed_at TEXT NOT NULL, as_of_at TEXT,
                last_price TEXT, currency TEXT NOT NULL, quality TEXT NOT NULL, status TEXT NOT NULL,
                source_hash TEXT NOT NULL, provider_fingerprint TEXT NOT NULL, vendor_time TEXT,
                bid_price TEXT, ask_price TEXT, midpoint TEXT, spread TEXT, order_book_as_of TEXT,
                order_book_status TEXT NOT NULL, market_session TEXT NOT NULL,
                subscription_mode TEXT NOT NULL,
                PRIMARY KEY(instrument_key, observed_at, source_hash)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO quote_snapshots VALUES (
                'US:SPY', '2026-01-02T15:00:00+00:00', NULL, '100', 'USD', 'real_time',
                'available', ?, ?, '2026-01-02 10:00:00', NULL, NULL, NULL, NULL, NULL,
                'absent', 'AFTERNOON', 'none'
            )
            """,
            ("e" * 64, "f" * 64),
        )

    snapshot = latest_quote_snapshots(ledger)["US:SPY"]

    assert snapshot.market_session is MarketSession.REGULAR
    assert snapshot.market_session_raw == "AFTERNOON"


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
