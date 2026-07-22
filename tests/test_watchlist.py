from __future__ import annotations

from conftest import encrypted_ledger

from stonks_cli.types import Currency, Instrument
from stonks_cli.watchlist import WatchlistItem, add, list_items, remove


def test_watchlist_items_are_encrypted_and_updatable(tmp_path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    item = WatchlistItem(Instrument("SPY", "US", Currency.USD, "S&P 500"), "core ETF")

    assert add(ledger, item) is True
    assert list_items(ledger) == (item,)
    assert add(ledger, WatchlistItem(item.instrument, "updated")) is True
    assert list_items(ledger)[0].note == "updated"
    assert remove(ledger, "us:spy") is True
    assert list_items(ledger) == ()
