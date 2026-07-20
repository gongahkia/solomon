from __future__ import annotations

from pathlib import Path

from stonks_cli.config import ProfileConfig
from stonks_cli.market_data import import_daily_prices_csv, latest_prices
from stonks_cli.storage import EncryptedLedger, generate_key_file


def test_price_import_keeps_latest_value(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    key = tmp_path / "key"
    generate_key_file(key)
    ledger = EncryptedLedger(ProfileConfig("personal", str(key)))
    source = tmp_path / "prices.csv"
    source.write_text(
        "date,symbol,market,currency,close\n2026-01-01,SPY,US,USD,100\n2026-01-02,SPY,US,USD,101\n"
    )
    assert import_daily_prices_csv(ledger, source) == 2
    assert str(latest_prices(ledger)["US:SPY"]) == "101"
