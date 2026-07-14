from __future__ import annotations

import json

from typer.testing import CliRunner

from stonks_cli.carry.carry_audit import CarryReconciliationMismatch, CarryReconciliationReport
from stonks_cli.carry.carry_live import (
    CarryLiveFillState,
    CarryLivePreflightEvidence,
    build_carry_live_entry_plan,
    build_carry_live_reduce_only_exit_plan,
    evaluate_carry_live_preflight,
    evaluate_carry_live_reconciliation,
    plan_carry_partial_fill_recovery,
)
from stonks_cli.cli import app
from stonks_cli.config import AppConfig
from stonks_cli.research.hyperliquid import HyperliquidCarryInput
from stonks_cli.research.models import BasisSnapshot, CarryDecision, CarryQuote, FundingSnapshot, Venue


def test_carry_live_preflight_fails_closed_by_default(tmp_path):
    cfg = AppConfig()

    result = evaluate_carry_live_preflight(
        cfg=cfg,
        evidence=CarryLivePreflightEvidence(requested_notional_usd=50, cap_usd=50, secrets_path=str(tmp_path / "missing.env")),
        env={},
    )

    assert result.ok is False
    assert "carry_live_config_not_armed" in result.blockers
    assert "carry_live_env_not_armed:STONKS_CLI_CARRY_LIVE_ARMED" in result.blockers
    assert "paper_gate_not_passed" in result.blockers
    assert "live_cap_not_configured" in result.blockers


def test_carry_live_preflight_passes_only_with_arm_cap_and_evidence(tmp_path):
    secrets = tmp_path / "carry-live.env"
    secrets.write_text("HYPERLIQUID_PRIVATE_KEY_ENV=EXAMPLE\n", encoding="utf-8")
    cfg = AppConfig.model_validate({"carry": {"live_armed": True, "max_total_live_usd": 100}})

    result = evaluate_carry_live_preflight(
        cfg=cfg,
        evidence=CarryLivePreflightEvidence(
            paper_gate_passed=True,
            legal_review_recorded=True,
            venue_health_ok=True,
            manual_cap_confirmed=True,
            requested_notional_usd=50,
            cap_usd=100,
            secrets_path=str(secrets),
        ),
        env={"STONKS_CLI_CARRY_LIVE_ARMED": "armed"},
    )

    assert result.ok is True
    assert result.blockers == []


def test_carry_live_preflight_blocks_manual_cap_mismatch(tmp_path):
    secrets = tmp_path / "carry-live.env"
    secrets.write_text("HYPERLIQUID_PRIVATE_KEY_ENV=EXAMPLE\n", encoding="utf-8")
    cfg = AppConfig.model_validate({"carry": {"live_armed": True, "max_total_live_usd": 50}})

    result = evaluate_carry_live_preflight(
        cfg=cfg,
        evidence=CarryLivePreflightEvidence(
            paper_gate_passed=True,
            legal_review_recorded=True,
            venue_health_ok=True,
            manual_cap_confirmed=True,
            requested_notional_usd=50,
            cap_usd=200,
            secrets_path=str(secrets),
        ),
        env={"STONKS_CLI_CARRY_LIVE_ARMED": "armed"},
    )

    assert result.ok is False
    assert "manual_cap_mismatch:200!=50.0" in result.blockers


def test_carry_live_cli_reports_preflight_blockers(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"carry": {"live_armed": False}}), encoding="utf-8")
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    result = CliRunner().invoke(app, ["preflight-carry-live", "--requested-notional-usd", "50", "--cap-usd", "50"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert "carry_live_config_not_armed" in payload["blockers"]


def test_carry_live_entry_plan_builds_matched_spot_and_perp_intents():
    plan = build_carry_live_entry_plan(
        inputs=_carry_input(),
        notional_usd=50,
        spot_asset_index=1,
        perp_asset_index=0,
        client_order_seed=42,
    )

    assert len(plan.orders) == 2
    assert plan.spot_order.asset_index == 10001
    assert plan.spot_order.is_buy is True
    assert plan.spot_order.tif == "Alo"
    assert plan.perp_order.asset_index == 0
    assert plan.perp_order.is_buy is False
    assert plan.perp_order.tif == "Alo"
    assert plan.spot_order.size == plan.perp_order.size
    assert plan.spot_order.cloid == "0x0000000000000000000000000000002b"


def test_carry_live_reduce_only_exit_plan_uses_perp_reduce_only():
    plan = build_carry_live_reduce_only_exit_plan(
        asset="BTC",
        spot_qty=0.01,
        perp_qty=-0.01,
        spot_asset_index=1,
        perp_asset_index=0,
        spot_limit_px=99900,
        perp_limit_px=100100,
    )

    assert plan.spot_order.is_buy is False
    assert plan.spot_order.reduce_only is False
    assert plan.perp_order.is_buy is True
    assert plan.perp_order.reduce_only is True
    assert plan.perp_order.tif == "Ioc"


def test_carry_live_reduce_only_exit_plan_blocks_unsupported_venue():
    try:
        build_carry_live_reduce_only_exit_plan(
            asset="BTC",
            spot_qty=0.01,
            perp_qty=-0.01,
            spot_asset_index=1,
            perp_asset_index=0,
            spot_limit_px=99900,
            perp_limit_px=100100,
            venue=Venue.BYBIT,
        )
    except ValueError as e:
        assert "unsupported_reduce_only_exit_venue:bybit" in str(e)
    else:
        raise AssertionError("unsupported venue should be blocked")


def test_carry_live_partial_fill_timeout_exits_unhedged_perp_reduce_only():
    recovery = plan_carry_partial_fill_recovery(
        fill_state=CarryLiveFillState(asset="BTC", spot_filled_qty=0.0, perp_filled_qty=-0.01, timed_out=True),
        spot_asset_index=1,
        perp_asset_index=0,
        spot_limit_px=99900,
        perp_limit_px=100100,
        max_delta_abs=0.000001,
    )

    assert recovery.action == "exit_unhedged_perp_reduce_only"
    assert recovery.orders[0].reduce_only is True
    assert recovery.orders[0].is_buy is True


def test_carry_live_reconciliation_blocks_mismatch_and_missing_ledger_row():
    report = CarryReconciliationReport(
        ok=False,
        blocks_live=True,
        mismatches=[CarryReconciliationMismatch(name="state_missing_position", inputs={"asset": "BTC"})],
    )
    decision = CarryDecision(
        decision_id="carry-live-1",
        mode="paper",
        action="paper_open",
        reason="fixture",
        inputs={},
        risk_checks=[],
        expected_net_apr=0.0,
        exit_rule="fixture",
        timestamp="2026-07-02T00:00:00Z",
    )

    gate = evaluate_carry_live_reconciliation(report=report, ledger_decisions=[decision], required_decision_ids=["carry-live-1", "missing"])

    assert gate.ok is False
    assert gate.blockers == ["reconciliation_blocks_live", "missing_ledger_row:missing"]


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
            hourly_rate=0.00001,
            annualized_rate=0.0876,
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
