from __future__ import annotations

from datetime import UTC, datetime, timedelta

from stonks_cli.config import AppConfig, PolymarketConfig
from stonks_cli.polymarket.exits import exit_decision
from stonks_cli.polymarket.models import PaperPosition


def test_exit_decision_target_hit():
    cfg = AppConfig(polymarket=PolymarketConfig(auto_exit_enabled=True))
    position = PaperPosition(
        token_id="YES1",
        market_id="1",
        slug="market-1",
        outcome="YES",
        shares=100,
        avg_price=0.50,
        opened_at="2026-01-01T00:00:00Z",
        target_price=0.65,
        stop_price=0.42,
    )

    decision = exit_decision(cfg, position, current_price=0.66)

    assert decision.should_exit is True
    assert decision.reason == "TARGET_HIT"


def test_exit_decision_stale_position_without_price():
    cfg = AppConfig(polymarket=PolymarketConfig(auto_exit_enabled=True, stale_position_hours=24))
    old = (datetime.now(UTC) - timedelta(hours=30)).isoformat().replace("+00:00", "Z")
    position = PaperPosition(
        token_id="YES1",
        market_id="1",
        slug="market-1",
        outcome="YES",
        shares=100,
        avg_price=0.50,
        opened_at=old,
    )

    decision = exit_decision(cfg, position, current_price=None)

    assert decision.should_exit is True
    assert decision.reason == "STALE_POSITION"
