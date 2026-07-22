from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from conftest import encrypted_ledger

from stonks_cli.market_data import (
    DailyPrice,
    archive_and_store_daily_prices,
    import_daily_prices_csv,
    latest_prices,
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


def test_market_refresh_archives_normalized_source(tmp_path: Path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    price = DailyPrice(Instrument("SPY", "US", Currency.USD), date(2026, 1, 1), Decimal("100"), "a" * 64)

    count, source_hash = archive_and_store_daily_prices(ledger, (price,))

    assert count == 1
    assert (ledger.sources / f"{source_hash}.enc").is_file()
