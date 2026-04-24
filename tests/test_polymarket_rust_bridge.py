from __future__ import annotations

from stonks_cli.config import AppConfig, PolymarketConfig
from stonks_cli.polymarket.models import LiveOrderRecord
from stonks_cli.polymarket.rust_bridge import RustHotPathSession


class _Bridge(RustHotPathSession):
    def __init__(self):
        super().__init__(AppConfig(polymarket=PolymarketConfig(enabled=True, rust_hotpath_enabled=True)))
        self.lines: list[str] = []

    def ensure_started(self) -> None:
        return None

    def _command(self, line: str) -> dict[str, str]:
        self.lines.append(line)
        if line.startswith("STALE "):
            return {"order_ids": "o1,o2"}
        return {"ok": "1"}


def test_rust_bridge_updates_book_and_resolution():
    bridge = _Bridge()

    bridge.apply_market_event({"event_type": "book", "asset_id": "YES1", "bids": [{"price": "0.41"}], "asks": [{"price": "0.43"}]})
    bridge.apply_market_event({"event_type": "tick_size_change", "asset_id": "YES1", "new_tick_size": "0.001"})
    bridge.apply_market_event(
        {
            "event_type": "market_resolved",
            "asset_id": "YES1",
            "winning_asset_id": "YES1",
            "winning_outcome": "YES",
        }
    )

    assert bridge.lines[0] == "BOOK token=YES1 bid=0.41 ask=0.43"
    assert "TICK token=YES1 size=0.001" in bridge.lines
    assert "RESOLVE token=YES1 winner=YES1 outcome=YES" in bridge.lines


def test_rust_bridge_applies_trade_and_order_events():
    bridge = _Bridge()

    trade_updates = bridge.apply_user_event(
        {
            "event_type": "trade",
            "status": "MATCHED",
            "timestamp": "2026-04-24T00:00:05Z",
            "maker_orders": [{"order_id": "maker-1", "matched_amount": "2.5"}],
            "taker_order_id": "taker-1",
            "size": "3.5",
        }
    )
    order_updates = bridge.apply_user_event(
        {
            "event_type": "order",
            "id": "order-1",
            "original_size": "12",
            "size_matched": "3",
            "type": "UPDATE",
            "timestamp": "2026-04-24T00:00:06Z",
        }
    )

    assert len(trade_updates) == 2
    assert any(line.startswith("TRADE id=maker-1 matched=2.5") for line in bridge.lines)
    assert any(line.startswith("TRADE id=taker-1 matched=3.5") for line in bridge.lines)
    assert len(order_updates) == 1
    assert any("FILL id=order-1 status=UPDATE" in line and "filled=3.0" in line and "remaining=9.0" in line for line in bridge.lines)


def test_rust_bridge_parses_stale_order_ids():
    bridge = _Bridge()

    order_ids = bridge.stale_orders(max_age_s=30, now_s=100)

    assert order_ids == ["o1", "o2"]


def test_rust_bridge_syncs_order_record():
    bridge = _Bridge()

    bridge.sync_order_record(
        LiveOrderRecord(
            order_id="order-1",
            token_id="YES1",
            market_id="m1",
            slug="btc-higher",
            outcome="YES",
            side="BUY",
            price=0.58,
            shares=12.0,
            status="OPEN",
            created_at="2026-04-24T00:00:00Z",
            updated_at="2026-04-24T00:00:05Z",
            remaining_shares=9.0,
            filled_shares=3.0,
        )
    )

    assert any(line.startswith("SYNCORDER id=order-1 token=YES1 market=m1 side=BUY price=0.58") for line in bridge.lines)
