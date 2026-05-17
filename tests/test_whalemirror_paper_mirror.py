from __future__ import annotations

from stonks_cli.whalemirror.attribution import rank_wallets_from_fixture
from stonks_cli.whalemirror.models import MirrorMode, NormalizedTrade, TradeSide, Venue
from stonks_cli.whalemirror.paper_mirror import (
    DEFAULT_PAPER_MIRROR_FIXTURE,
    PaperMirrorConfig,
    PaperMirrorEngine,
    replay_paper_mirror_fixture,
)


def _rankings():
    return rank_wallets_from_fixture(limit=5)


def test_paper_mirror_sizes_against_follower_bankroll_not_source_wallet():
    engine = PaperMirrorEngine(
        rankings=_rankings(),
        config=PaperMirrorConfig(follower_bankroll_usd=1000, max_position_fraction=0.05, max_order_notional_usd=75),
    )
    trade = NormalizedTrade(
        venue=Venue.HYPERLIQUID,
        trade_id="source-1",
        wallet="0xaaa0000000000000000000000000000000000001",
        market="BTC-PERP",
        asset="BTC",
        side=TradeSide.BUY,
        price=65000.0,
        size=0.5,
        notional_usd=32500.0,
        observed_at="2026-02-02T02:40:00Z",
    )

    decision = engine.process_trade(trade)

    assert decision.intent is not None
    assert decision.intent.mode is MirrorMode.PAPER
    assert decision.intent.notional_usd == 50.0
    assert decision.intent.metadata["target_notional_usd"] == 32500.0
    assert decision.intent.metadata["bankroll_position_cap_usd"] == 50.0
    assert decision.intent.metadata["size_down_ratio"] < 0.01
    assert decision.ledger_record.metadata["execution_intent"]["mode"] == "paper"


def test_stop_loss_sets_reentry_cooldown_and_blocks_next_trade():
    engine = PaperMirrorEngine(
        rankings=_rankings(),
        config=PaperMirrorConfig(follower_bankroll_usd=1000, max_position_fraction=0.10, cooldown_minutes=60),
    )
    trade = NormalizedTrade(
        venue=Venue.HYPERLIQUID,
        trade_id="source-1",
        wallet="0xaaa0000000000000000000000000000000000001",
        market="BTC-PERP",
        asset="BTC",
        side=TradeSide.BUY,
        price=65000.0,
        size=0.02,
        notional_usd=1300.0,
        observed_at="2026-02-02T02:40:00Z",
    )
    engine.process_trade(trade)

    stop_decisions = engine.process_mark(market="BTC-PERP", mark_px=59000.0, timestamp_utc="2026-02-02T02:45:00Z")
    blocked = engine.process_trade(
        NormalizedTrade(
            venue=Venue.HYPERLIQUID,
            trade_id="source-2",
            wallet=trade.wallet,
            market="BTC-PERP",
            asset="BTC",
            side=TradeSide.BUY,
            price=59100.0,
            size=0.02,
            notional_usd=1182.0,
            observed_at="2026-02-02T03:00:00Z",
        )
    )

    assert stop_decisions[0].ledger_record.decision == "paper_stop_loss"
    assert stop_decisions[0].ledger_record.metadata["risk_control"] == "stop_loss"
    assert stop_decisions[0].ledger_record.metadata["cooldown_until"] == "2026-02-02T03:45:00Z"
    assert blocked.intent is None
    assert blocked.ledger_record.decision == "skip_cooldown"
    assert blocked.ledger_record.metadata["risk_control"] == "cooldown"


def test_replay_fixture_produces_realistic_tearsheet_and_ledger_controls():
    replay = replay_paper_mirror_fixture(
        fixture_path=DEFAULT_PAPER_MIRROR_FIXTURE,
        rankings=_rankings(),
        config=PaperMirrorConfig(follower_bankroll_usd=1000, max_position_fraction=0.10, max_order_notional_usd=75),
    )
    decisions = [decision.ledger_record for decision in replay.decisions]

    assert replay.tearsheet["closed_trades"] == 2
    assert replay.tearsheet["wins"] == 1
    assert replay.tearsheet["losses"] == 1
    assert replay.tearsheet["cooldowns_active"] == 1
    assert any(record.decision == "paper_mirror_open" for record in decisions)
    assert any(record.decision == "paper_stop_loss" for record in decisions)
    assert any(record.decision == "skip_cooldown" for record in decisions)
    assert all(record.mode is MirrorMode.PAPER for record in decisions)
    assert decisions[0].metadata["risk_controls"]["mirror_notional_usd"] == 75.0
