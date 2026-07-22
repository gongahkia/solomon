from __future__ import annotations

from conftest import encrypted_ledger

from stonks_cli.types import Currency, Instrument
from stonks_cli.watchlist import (
    WatchlistItem,
    add,
    audit_history,
    configure_restriction,
    list_items,
    recommendation_allowed,
    remove,
    settings,
)


def test_watchlist_items_are_encrypted_and_updatable(tmp_path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    item = WatchlistItem(Instrument("SPY", "US", Currency.USD, "S&P 500"), "core ETF")

    assert add(ledger, item) is True
    assert list_items(ledger) == (item,)
    assert add(ledger, WatchlistItem(item.instrument, "updated")) is True
    assert list_items(ledger)[0].note == "updated"
    assert remove(ledger, "us:spy") is True
    assert list_items(ledger) == ()


def test_watchlist_restriction_is_versioned_audited_and_fail_closed(tmp_path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    allowed = Instrument("SPY", "US", Currency.USD)
    excluded = Instrument("QQQ", "US", Currency.USD)

    assert settings(ledger).restriction_enabled is False
    assert recommendation_allowed(ledger, excluded) is True
    assert add(ledger, WatchlistItem(allowed), source="operator") is True
    assert settings(ledger).version == 2
    enabled = configure_restriction(ledger, True, source="settings")
    assert enabled.version == 3
    assert recommendation_allowed(ledger, allowed) is True
    assert recommendation_allowed(ledger, excluded) is False
    assert configure_restriction(ledger, True, source="settings") == enabled
    assert add(ledger, WatchlistItem(allowed), source="operator") is False
    assert remove(ledger, allowed.key, source="operator") is True
    history = audit_history(ledger)
    assert [entry.action for entry in history] == ["added", "restriction_enabled", "removed"]
    assert [entry.configuration_version for entry in history] == [2, 3, 4]
    assert history[0].source == "operator"
    assert history[0].item == WatchlistItem(allowed)
    assert history[1].item is None
    assert history[2].restriction_enabled is True
