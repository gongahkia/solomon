from __future__ import annotations

import pytest

from stonks_cli.research.guards import evaluate_execution_guards, live_arm_env, live_execution_armed
from stonks_cli.research.journal import append_decision, read_decisions
from stonks_cli.research.models import (
    BasisSnapshot,
    CarryDecision,
    CarryOpportunity,
    CarryPosition,
    CarryQuote,
    DecisionRecord,
    ExecutionMode,
    FundingSnapshot,
    NormalizedTrade,
    Venue,
)


def test_hyperliquid_live_arm_gate_fails_closed(monkeypatch):
    monkeypatch.delenv("STONKS_CLI_HYPERLIQUID_LIVE_ARMED", raising=False)

    assert live_arm_env(Venue.HYPERLIQUID) == "STONKS_CLI_HYPERLIQUID_LIVE_ARMED"
    assert live_execution_armed(Venue.HYPERLIQUID) is False

    reasons = evaluate_execution_guards(venue=Venue.HYPERLIQUID, mode=ExecutionMode.LIVE)
    assert reasons == ["live_trading_not_armed:STONKS_CLI_HYPERLIQUID_LIVE_ARMED"]

    monkeypatch.setenv("STONKS_CLI_HYPERLIQUID_LIVE_ARMED", "armed")
    assert live_execution_armed("hyperliquid") is True
    assert evaluate_execution_guards(venue="hyperliquid", mode="live") == []


def test_sg_blocked_venues_cannot_be_live_executed(monkeypatch):
    monkeypatch.setenv("STONKS_CLI_POLYMARKET_LIVE_ARMED", "armed")

    reasons = evaluate_execution_guards(venue=Venue.POLYMARKET, mode=ExecutionMode.LIVE)

    assert "venue_blocked_for_sg:polymarket" in reasons


def test_bybit_and_wallet_live_target_strategy_are_sg_blocked(monkeypatch):
    monkeypatch.setenv("STONKS_CLI_BYBIT_LIVE_ARMED", "armed")

    reasons = evaluate_execution_guards(
        venue=Venue.BYBIT,
        mode=ExecutionMode.LIVE,
        strategy_class="wallet-live-target-selection",
    )

    assert "venue_blocked_for_sg:bybit" in reasons
    assert "strategy_blocked_for_sg:wallet_live_target_selection" in reasons


def test_paper_mode_does_not_require_live_arm():
    assert evaluate_execution_guards(venue=Venue.HYPERLIQUID, mode=ExecutionMode.PAPER) == []


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


def test_research_decision_journal_roundtrip(tmp_path):
    path = tmp_path / "decisions.jsonl"
    append_decision(
        DecisionRecord(
            timestamp_utc="2026-05-17T00:00:00Z",
            mode=ExecutionMode.PAPER,
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


def test_carry_models_serialize_deterministically():
    quote = CarryQuote(
        venue="hyperliquid",
        asset="BTC",
        spot_mid=100000.0,
        perp_mid=100100.0,
        oracle_mid=100050.0,
        mark_mid=100090.0,
        timestamp="2026-07-02T00:00:00Z",
        source_health="ok",
    )
    funding = FundingSnapshot(
        asset="BTC",
        venue=Venue.HYPERLIQUID,
        hourly_rate=0.0001,
        annualized_rate=0.876,
        next_funding_time="2026-07-02T01:00:00Z",
        premium_index=0.001,
        timestamp="2026-07-02T00:00:00Z",
    )
    basis = BasisSnapshot(
        asset="BTC",
        spot_mid=100000.0,
        perp_mid=100100.0,
        basis_abs=100.0,
        basis_pct=0.001,
        annualized_basis=0.365,
        timestamp="2026-07-02T00:00:00Z",
    )
    opportunity = CarryOpportunity(
        asset="BTC",
        venue="hyperliquid",
        direction="long_spot_short_perp",
        net_apr=0.18,
        gross_apr=0.21,
        fee_bps=2.0,
        slippage_bps=3.0,
        buffer_bps=5.0,
    )
    position = CarryPosition(
        asset="BTC",
        spot_qty=0.01,
        perp_qty=-0.01,
        net_delta=0.0,
        entry_basis=0.001,
        accrued_funding=1.25,
        fees=0.35,
        margin_buffer=0.25,
        liquidation_distance=0.40,
    )
    decision = CarryDecision(
        decision_id="carry-001",
        mode="paper",
        action="open",
        reason="net_apr_above_research_threshold",
        inputs={"z": 1, "a": 2},
        risk_checks=["paper_only", "delta_neutral"],
        expected_net_apr=0.18,
        exit_rule="net_apr_below_threshold",
        timestamp="2026-07-02T00:00:00Z",
    )

    assert quote.to_dict()["venue"] == "hyperliquid"
    assert funding.to_dict()["venue"] == "hyperliquid"
    assert basis.to_dict()["basis_abs"] == 100.0
    assert opportunity.to_dict()["required_fields_missing"] == []
    assert position.to_dict()["net_delta"] == 0.0
    assert list(decision.to_dict()["inputs"]) == ["a", "z"]
    assert decision.to_dict()["mode"] == "paper"


def test_carry_models_report_missing_scanner_fields():
    opportunity = CarryOpportunity(
        asset="ETH",
        venue="hyperliquid",
        direction="skip",
        net_apr=0.0,
        gross_apr=0.0,
        fee_bps=0.0,
        slippage_bps=0.0,
        buffer_bps=0.0,
        required_fields_missing=["oracle_mid", "next_funding_time"],
    )

    assert opportunity.to_dict()["required_fields_missing"] == ["oracle_mid", "next_funding_time"]


def test_carry_required_fields_fail_fast():
    with pytest.raises(TypeError):
        CarryQuote(asset="BTC")  # type: ignore[call-arg]
