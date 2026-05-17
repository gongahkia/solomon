from __future__ import annotations

from stonks_cli.config import AppConfig
from stonks_cli.whalemirror.guards import evaluate_execution_guards, live_arm_env, live_execution_armed
from stonks_cli.whalemirror.journal import append_decision, read_decisions
from stonks_cli.whalemirror.models import DecisionRecord, MirrorMode, NormalizedTrade, Venue


def test_hyperliquid_live_arm_gate_fails_closed(monkeypatch):
    monkeypatch.delenv("STONKS_CLI_HYPERLIQUID_LIVE_ARMED", raising=False)

    assert live_arm_env(Venue.HYPERLIQUID) == "STONKS_CLI_HYPERLIQUID_LIVE_ARMED"
    assert live_execution_armed(Venue.HYPERLIQUID) is False

    reasons = evaluate_execution_guards(venue=Venue.HYPERLIQUID, mode=MirrorMode.LIVE)
    assert reasons == ["live_trading_not_armed:STONKS_CLI_HYPERLIQUID_LIVE_ARMED"]

    monkeypatch.setenv("STONKS_CLI_HYPERLIQUID_LIVE_ARMED", "armed")
    assert live_execution_armed("hyperliquid") is True
    assert evaluate_execution_guards(venue="hyperliquid", mode="live") == []


def test_sg_blocked_venues_cannot_be_live_executed(monkeypatch):
    monkeypatch.setenv("STONKS_CLI_POLYMARKET_LIVE_ARMED", "armed")

    reasons = evaluate_execution_guards(venue=Venue.POLYMARKET, mode=MirrorMode.LIVE)

    assert "venue_blocked_for_sg:polymarket" in reasons


def test_paper_mode_does_not_require_live_arm():
    assert evaluate_execution_guards(venue=Venue.HYPERLIQUID, mode=MirrorMode.PAPER) == []


def test_normalized_trade_is_json_ready():
    trade = NormalizedTrade(
        venue="hyperliquid",
        trade_id="t-1",
        wallet="0xabc",
        market="BTC-PERP",
        asset="BTC",
        side="buy",
        price=100000.0,
        size=0.01,
        notional_usd=1000.0,
        observed_at="2026-05-17T00:00:00Z",
    )

    payload = trade.to_dict()

    assert payload["venue"] == "hyperliquid"
    assert payload["side"] == "buy"
    assert payload["notional_usd"] == 1000.0


def test_whalemirror_decision_journal_roundtrip(tmp_path):
    path = tmp_path / "decisions.jsonl"
    append_decision(
        DecisionRecord(
            timestamp_utc="2026-05-17T00:00:00Z",
            mode=MirrorMode.PAPER,
            venue=Venue.HYPERLIQUID,
            signal="fixture-wallet",
            decision="mirror_buy",
            rationale="fixture replay",
            receipt="paper:1",
            outcome="pending",
        ),
        path=path,
    )

    rows = read_decisions(path=path)

    assert rows == [
        {
            "decision": "mirror_buy",
            "metadata": {},
            "mode": "paper",
            "outcome": "pending",
            "rationale": "fixture replay",
            "receipt": "paper:1",
            "signal": "fixture-wallet",
            "timestamp_utc": "2026-05-17T00:00:00Z",
            "venue": "hyperliquid",
        }
    ]


def test_config_exposes_whalemirror_hyperliquid_gate():
    cfg = AppConfig()

    assert cfg.whalemirror.venue == "hyperliquid"
    assert cfg.whalemirror.hyperliquid_live_armed_env == "STONKS_CLI_HYPERLIQUID_LIVE_ARMED"
    assert cfg.whalemirror.max_live_order_notional_usd == 50.0
