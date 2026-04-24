from __future__ import annotations

from stonks_cli.polymarket.models import BookLevel, LiveMarketSnapshot, OrderBook
from stonks_cli.polymarket.stream import MarketStateCache, reduce_market_event, snapshot_from_book


def test_snapshot_from_book_preserves_best_levels():
    snapshot = snapshot_from_book(
        OrderBook(
            token_id="YES1",
            bids=[BookLevel(price=0.52, size=1000)],
            asks=[BookLevel(price=0.54, size=900)],
            midpoint=0.53,
            best_bid=0.52,
            best_ask=0.54,
            raw={"tick_size": "0.01"},
        )
    )

    assert snapshot.token_id == "YES1"
    assert snapshot.best_bid == 0.52
    assert snapshot.best_ask == 0.54
    assert snapshot.midpoint == 0.53
    assert snapshot.tick_size == 0.01


def test_reduce_market_event_updates_book_and_tick_size():
    updated = reduce_market_event(
        None,
        {
            "event_type": "book",
            "asset_id": "YES1",
            "bids": [{"price": 0.60, "size": 200}],
            "asks": [{"price": 0.62, "size": 300}],
            "tick_size": "0.02",
        },
    )

    assert updated.best_bid == 0.60
    assert updated.best_ask == 0.62
    assert updated.midpoint == 0.61
    assert updated.tick_size == 0.02


def test_reduce_market_event_marks_market_resolved():
    snapshot = LiveMarketSnapshot(token_id="YES1", best_bid=0.4, best_ask=0.5)

    updated = reduce_market_event(
        snapshot,
        {
            "event_type": "market_resolved",
            "asset_id": "YES1",
            "winning_asset_id": "YES1",
            "winning_outcome": "YES",
        },
    )

    assert updated.resolved is True
    assert updated.winning_token_id == "YES1"
    assert updated.winning_outcome == "YES"
    assert updated.last_event_type == "market_resolved"


def test_market_state_cache_keeps_latest_snapshot():
    cache = MarketStateCache()

    cache.apply({"event_type": "best_bid_ask", "asset_id": "YES1", "best_bid": "0.41", "best_ask": "0.43"})
    cache.apply({"event_type": "last_trade_price", "asset_id": "YES1", "price": "0.42"})

    snapshot = cache.get("YES1")
    assert snapshot is not None
    assert snapshot.best_bid == 0.41
    assert snapshot.best_ask == 0.43
    assert snapshot.last_trade_price == 0.42
