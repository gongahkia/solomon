from __future__ import annotations

import json

from typer.testing import CliRunner

from stonks_cli.carry.carry_paper import PaperCarryConfig, PaperCarryEngine
from stonks_cli.cli import app
from stonks_cli.research.hyperliquid import HyperliquidCarryInput
from stonks_cli.research.models import BasisSnapshot, CarryQuote, FundingSnapshot, Venue


def test_paper_carry_enters_positive_funding_delta_neutral_position():
    engine = PaperCarryEngine(min_net_apr=0.15, config=PaperCarryConfig(position_notional_usd=100))

    decision = engine.process_input(_carry_input(annualized_rate=0.22))

    position = engine.state.positions["BTC"]
    assert decision.action == "paper_open"
    assert decision.mode == "paper"
    assert position.spot_qty > 0
    assert position.perp_qty < 0
    assert abs(position.net_delta) == 0.0
    assert position.fees > 0
    assert position.slippage > 0
    assert position.margin_buffer == 0.35
    assert position.liquidation_distance == 0.50


def test_paper_carry_skips_negative_funding_without_live_orders():
    engine = PaperCarryEngine(min_net_apr=0.15)

    decision = engine.process_input(_carry_input(annualized_rate=-0.05))

    assert decision.action == "skip_negative_funding"
    assert decision.mode == "paper"
    assert engine.state.positions == {}


def test_paper_carry_accrues_funding_and_exits_on_funding_flip():
    engine = PaperCarryEngine(min_net_apr=0.15, config=PaperCarryConfig(position_notional_usd=100))
    engine.process_input(_carry_input(annualized_rate=0.22, timestamp="2026-07-02T00:00:00Z"))
    engine.accrue_funding(asset="BTC", hourly_rate=0.0001, mark_px=100090.0, hours=1)

    decision = engine.process_input(_carry_input(annualized_rate=-0.05, timestamp="2026-07-02T01:00:00Z"))

    closed = engine.state.closed_positions[0]
    assert decision.action == "paper_exit"
    assert decision.reason == "funding_flip"
    assert closed.exit_reason == "funding_flip"
    assert closed.accrued_funding != 0.0
    assert closed.fees > 0
    assert closed.slippage > 0
    assert "BTC" not in engine.state.positions


def test_carry_paper_run_cli_writes_state_report_and_ledger(tmp_path, monkeypatch):
    fixture = tmp_path / "carry-inputs.json"
    cfg_path = tmp_path / "config.json"
    state_dir = tmp_path / "state"
    report = tmp_path / "paper.md"
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))
    fixture.write_text(json.dumps({"inputs": [_carry_input(annualized_rate=0.22).to_dict()]}), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "run-carry-paper",
            "--fixture",
            str(fixture),
            "--state-dir",
            str(state_dir),
            "--report",
            str(report),
            "--ledger",
            str(ledger),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["paper"] is True
    assert payload["summary"]["open_positions"] == 1
    assert report.read_text(encoding="utf-8").startswith("# Carry Paper Run")
    assert "paper_open" in ledger.read_text(encoding="utf-8")
    assert (state_dir / "carry-paper-state.json").exists()


def _carry_input(*, annualized_rate: float, timestamp: str = "2026-07-02T00:00:00Z") -> HyperliquidCarryInput:
    return HyperliquidCarryInput(
        asset="BTC",
        quote=CarryQuote(
            venue=Venue.HYPERLIQUID,
            asset="BTC",
            spot_mid=100000.0,
            perp_mid=100100.0,
            oracle_mid=100050.0,
            mark_mid=100090.0,
            timestamp=timestamp,
            source_health="ok",
        ),
        funding=FundingSnapshot(
            asset="BTC",
            venue=Venue.HYPERLIQUID,
            hourly_rate=annualized_rate / (24 * 365),
            annualized_rate=annualized_rate,
            next_funding_time=None,
            premium_index=0.001,
            timestamp=timestamp,
        ),
        basis=BasisSnapshot(
            asset="BTC",
            spot_mid=100000.0,
            perp_mid=100100.0,
            basis_abs=100.0,
            basis_pct=0.001,
            annualized_basis=0.0,
            timestamp=timestamp,
        ),
        metadata={"perp": {"name": "BTC"}, "spot": {"name": "BTC/USDC"}},
        source_health={"all_mids": "ok", "perp_context": "ok", "spot_context": "ok"},
    )
