from __future__ import annotations

from stonks_cli.carry.carry_paper import PaperCarryConfig, PaperCarryEngine
from stonks_cli.carry.carry_risk import CarryRiskLimits, CarryRiskState, evaluate_carry_risk
from stonks_cli.config import AppConfig
from stonks_cli.research.hyperliquid import HyperliquidCarryInput
from stonks_cli.research.models import BasisSnapshot, CarryQuote, FundingSnapshot, Venue


def test_carry_risk_blocks_stale_data():
    assessment = evaluate_carry_risk(
        _risk_state(websocket_age_seconds=31.0, rest_age_seconds=45.0),
        CarryRiskLimits(max_data_age_seconds=30.0),
    )

    assert assessment.risk_checks == ["stale_websocket_data", "stale_rest_data"]
    assert assessment.breaches[0].inputs["websocket_age_seconds"] == 31.0
    assert assessment.breaches[1].inputs["rest_age_seconds"] == 45.0


def test_carry_risk_blocks_max_notional_and_drawdowns():
    assessment = evaluate_carry_risk(
        _risk_state(notional_usd=250.0, daily_drawdown_pct=0.006, weekly_drawdown_pct=0.02, global_drawdown_pct=0.04),
        CarryRiskLimits(max_notional_usd=200.0),
    )

    assert assessment.risk_checks == ["max_notional", "daily_drawdown", "weekly_drawdown", "global_drawdown"]
    assert assessment.breaches[0].inputs["notional_usd"] == 250.0


def test_carry_risk_blocks_delta_drift_and_missing_hedge():
    assessment = evaluate_carry_risk(
        _risk_state(net_delta=0.01, spot_qty=0.01, perp_qty=0.0, hedge_present=False),
        CarryRiskLimits(max_delta_abs=0.001),
    )

    assert assessment.risk_checks == ["delta_drift", "missing_hedge"]
    assert assessment.breaches[0].inputs["net_delta"] == 0.01
    assert assessment.breaches[1].inputs["hedge_present"] is False


def test_carry_risk_blocks_strategy_live_cap_raise():
    assessment = evaluate_carry_risk(
        _risk_state(configured_live_cap_usd=50.0, strategy_requested_live_cap_usd=75.0),
    )

    assert assessment.risk_checks == ["no_auto_raise_live_cap"]
    assert assessment.breaches[0].inputs == {
        "configured_live_cap_usd": 50.0,
        "strategy_requested_live_cap_usd": 75.0,
    }


def test_carry_paper_blocked_decision_includes_risk_names_and_inputs():
    engine = PaperCarryEngine(
        min_net_apr=0.15,
        config=PaperCarryConfig(position_notional_usd=100.0, risk_limits=CarryRiskLimits(max_notional_usd=50.0)),
    )

    decision = engine.process_input(_carry_input())

    assert decision.action == "skip_risk_firewall"
    assert decision.risk_checks == ["max_notional"]
    assert decision.inputs["risk_assessment"]["risk_checks"] == ["max_notional"]
    assert decision.inputs["risk_assessment"]["breaches"][0]["inputs"]["notional_usd"] == 100.0
    assert engine.state.positions == {}


def test_carry_config_exposes_default_risk_limits():
    cfg = AppConfig()

    assert cfg.carry.max_data_age_seconds == 30.0
    assert cfg.carry.daily_drawdown_limit_pct == 0.005
    assert cfg.carry.weekly_drawdown_limit_pct == 0.015
    assert cfg.carry.global_drawdown_limit_pct == 0.03


def _risk_state(**overrides) -> CarryRiskState:
    values = {
        "asset": "BTC",
        "configured_live_cap_usd": 0.0,
        "daily_drawdown_pct": 0.0,
        "global_drawdown_pct": 0.0,
        "hedge_present": True,
        "liquidation_distance": 0.50,
        "margin_buffer": 0.35,
        "net_delta": 0.0,
        "notional_usd": 100.0,
        "perp_qty": -0.001,
        "rest_age_seconds": 0.0,
        "spot_qty": 0.001,
        "strategy_requested_live_cap_usd": 0.0,
        "websocket_age_seconds": 0.0,
        "weekly_drawdown_pct": 0.0,
    }
    values.update(overrides)
    return CarryRiskState(**values)


def _carry_input() -> HyperliquidCarryInput:
    return HyperliquidCarryInput(
        asset="BTC",
        quote=CarryQuote(
            venue=Venue.HYPERLIQUID,
            asset="BTC",
            spot_mid=100000.0,
            perp_mid=100100.0,
            oracle_mid=100050.0,
            mark_mid=100090.0,
            timestamp="2026-07-02T00:00:00Z",
            source_health="ok",
        ),
        funding=FundingSnapshot(
            asset="BTC",
            venue=Venue.HYPERLIQUID,
            hourly_rate=0.22 / (24 * 365),
            annualized_rate=0.22,
            next_funding_time=None,
            premium_index=0.001,
            timestamp="2026-07-02T00:00:00Z",
        ),
        basis=BasisSnapshot(
            asset="BTC",
            spot_mid=100000.0,
            perp_mid=100100.0,
            basis_abs=100.0,
            basis_pct=0.001,
            annualized_basis=0.0,
            timestamp="2026-07-02T00:00:00Z",
        ),
        metadata={"perp": {"name": "BTC"}, "spot": {"name": "BTC/USDC"}},
        source_health={"all_mids": "ok", "perp_context": "ok", "spot_context": "ok"},
    )
