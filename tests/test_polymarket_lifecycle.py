from __future__ import annotations

import pytest

from stonks_cli.config import AppConfig, PolymarketConfig
from stonks_cli.polymarket.execution import ExecutionOrder
from stonks_cli.polymarket.lifecycle import (
    LiveOrderManager,
    build_live_order_request,
    load_live_orders,
    normalize_price_to_tick,
)
from stonks_cli.polymarket.models import LiveMarketSnapshot


def test_normalize_price_to_tick_is_side_aware():
    assert normalize_price_to_tick(0.537, tick_size=0.01, side="BUY") == 0.53
    assert normalize_price_to_tick(0.537, tick_size=0.01, side="SELL") == 0.54
    assert normalize_price_to_tick(0.58, tick_size=0.01, side="BUY") == 0.58


def test_build_live_order_request_rejects_post_only_cross():
    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=False, live_post_only=True))
    order = ExecutionOrder(
        token_id="YES1",
        market_id="1",
        slug="btc-higher",
        outcome="YES",
        side="BUY",
        price=0.61,
        shares=10,
    )
    snapshot = LiveMarketSnapshot(token_id="YES1", best_bid=0.58, best_ask=0.60, tick_size=0.01)

    try:
        build_live_order_request(cfg, order, snapshot)
    except ValueError as exc:
        assert "cross the spread" in str(exc)
    else:
        raise AssertionError("expected post-only rejection")


def test_build_live_order_request_snaps_to_tick_and_accepts_safe_order():
    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=False, live_post_only=True))
    order = ExecutionOrder(
        token_id="YES1",
        market_id="1",
        slug="btc-higher",
        outcome="YES",
        side="BUY",
        price=0.589,
        shares=10,
    )
    snapshot = LiveMarketSnapshot(token_id="YES1", best_bid=0.58, best_ask=0.60, tick_size=0.01)

    request = build_live_order_request(cfg, order, snapshot)

    assert request.price == 0.58
    assert request.post_only is True


def test_build_live_order_request_rejects_resolved_market():
    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=False, live_post_only=True))
    order = ExecutionOrder(
        token_id="YES1",
        market_id="1",
        slug="btc-higher",
        outcome="YES",
        side="BUY",
        price=0.58,
        shares=10,
    )
    snapshot = LiveMarketSnapshot(token_id="YES1", best_bid=0.57, best_ask=0.60, tick_size=0.01, resolved=True)

    with pytest.raises(ValueError, match="resolved"):
        build_live_order_request(cfg, order, snapshot)


def test_build_live_order_request_rejects_below_min_order_size():
    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=False, live_post_only=True))
    order = ExecutionOrder(
        token_id="YES1",
        market_id="1",
        slug="btc-higher",
        outcome="YES",
        side="BUY",
        price=0.58,
        shares=2,
    )
    snapshot = LiveMarketSnapshot(token_id="YES1", best_bid=0.57, best_ask=0.60, tick_size=0.01, min_order_size=5)

    with pytest.raises(ValueError, match="below venue minimum"):
        build_live_order_request(cfg, order, snapshot)


def test_live_order_manager_persists_and_marks_stale_cancel(monkeypatch, tmp_path):
    from stonks_cli.polymarket import lifecycle

    monkeypatch.setattr(lifecycle, "default_state_dir", lambda: tmp_path)

    cfg = AppConfig(
        polymarket=PolymarketConfig(
            enabled=True,
            paper=False,
            live_order_max_age_seconds=30,
        )
    )
    manager = LiveOrderManager(cfg)
    record = manager.register_submitted(
        "order-1",
        build_live_order_request(
            cfg,
            ExecutionOrder(
                token_id="YES1",
                market_id="1",
                slug="btc-higher",
                outcome="YES",
                side="BUY",
                price=0.58,
                shares=12,
            ),
            LiveMarketSnapshot(token_id="YES1", best_bid=0.57, best_ask=0.60, tick_size=0.01),
        ),
        now="2026-04-24T00:00:00Z",
    )

    actions = manager.stale_cancels(now="2026-04-24T00:01:00Z")

    assert record.status == "OPEN"
    assert [action.action for action in actions] == ["CANCEL"]
    assert load_live_orders()[0].order_id == "order-1"


def test_live_order_manager_applies_fill_event(monkeypatch, tmp_path):
    from stonks_cli.polymarket import lifecycle

    monkeypatch.setattr(lifecycle, "default_state_dir", lambda: tmp_path)

    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=False))
    manager = LiveOrderManager(cfg)
    manager.register_submitted(
        "order-1",
        build_live_order_request(
            cfg,
            ExecutionOrder(
                token_id="YES1",
                market_id="1",
                slug="btc-higher",
                outcome="YES",
                side="BUY",
                price=0.58,
                shares=12,
            ),
            LiveMarketSnapshot(token_id="YES1", best_bid=0.57, best_ask=0.60, tick_size=0.01),
        ),
        now="2026-04-24T00:00:00Z",
    )

    updated = manager.apply_user_event(
        {
            "order_id": "order-1",
            "status": "FILLED",
            "filled_size": 12,
            "remaining_size": 0,
            "timestamp": "2026-04-24T00:00:05Z",
        }
    )

    assert updated is not None
    assert updated.status == "FILLED"
    assert updated.filled_shares == 12
    assert updated.remaining_shares == 0


def test_live_order_manager_syncs_open_order_snapshot(monkeypatch, tmp_path):
    from stonks_cli.polymarket import lifecycle

    monkeypatch.setattr(lifecycle, "default_state_dir", lambda: tmp_path)

    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=False))
    manager = LiveOrderManager(cfg)
    manager.register_submitted(
        "order-1",
        build_live_order_request(
            cfg,
            ExecutionOrder(
                token_id="YES1",
                market_id="1",
                slug="btc-higher",
                outcome="YES",
                side="BUY",
                price=0.58,
                shares=12,
            ),
            LiveMarketSnapshot(token_id="YES1", best_bid=0.57, best_ask=0.60, tick_size=0.01),
        ),
        now="2026-04-24T00:00:00Z",
    )

    synced = manager.sync_open_orders(
        [
            {
                "id": "order-1",
                "asset_id": "YES1",
                "market": "1",
                "side": "BUY",
                "price": "0.58",
                "original_size": "12",
                "size_matched": "4",
                "status": "OPEN",
            }
        ],
        now="2026-04-24T00:00:10Z",
    )

    assert len(synced) == 1
    assert synced[0].filled_shares == 4
    assert synced[0].remaining_shares == 8


def test_live_order_manager_applies_trade_maker_fill(monkeypatch, tmp_path):
    from stonks_cli.polymarket import lifecycle

    monkeypatch.setattr(lifecycle, "default_state_dir", lambda: tmp_path)

    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=False))
    manager = LiveOrderManager(cfg)
    manager.register_submitted(
        "order-1",
        build_live_order_request(
            cfg,
            ExecutionOrder(
                token_id="YES1",
                market_id="1",
                slug="btc-higher",
                outcome="YES",
                side="SELL",
                price=0.61,
                shares=12,
            ),
            LiveMarketSnapshot(token_id="YES1", best_bid=0.57, best_ask=0.63, tick_size=0.01),
        ),
        now="2026-04-24T00:00:00Z",
    )

    updated = manager.apply_user_event(
        {
            "event_type": "trade",
            "status": "MATCHED",
            "maker_orders": [{"order_id": "order-1", "matched_amount": "5"}],
            "timestamp": "2026-04-24T00:00:05Z",
        }
    )

    assert updated is not None
    assert updated.filled_shares == 5
    assert updated.remaining_shares == 7
