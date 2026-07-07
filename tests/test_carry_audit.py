from __future__ import annotations

from stonks_cli.whalemirror.carry_audit import (
    carry_ledger_row,
    reconcile_carry_state,
    render_carry_ledger,
    render_carry_reconciliation_report,
)
from stonks_cli.whalemirror.carry_paper import PaperCarryConfig, PaperCarryEngine
from stonks_cli.whalemirror.hyperliquid import HyperliquidCarryInput
from stonks_cli.whalemirror.models import BasisSnapshot, CarryQuote, FundingSnapshot, Venue


def test_carry_ledger_rows_cover_skip_entry_exit_and_kill():
    skip_engine = PaperCarryEngine(min_net_apr=0.15)
    skip = skip_engine.process_input(_carry_input(annualized_rate=-0.05))
    entry_engine = PaperCarryEngine(min_net_apr=0.15)
    entry = entry_engine.process_input(_carry_input(annualized_rate=0.22))
    exit_decision = entry_engine.process_input(_carry_input(annualized_rate=-0.05, timestamp="2026-07-02T01:00:00Z"))
    kill_engine = PaperCarryEngine(min_net_apr=0.15, config=PaperCarryConfig(kill_switch_active=True))
    kill = kill_engine.process_input(_carry_input(annualized_rate=0.22))

    ledger = render_carry_ledger([skip, entry, exit_decision, kill])
    entry_row = carry_ledger_row(entry)
    exit_row = carry_ledger_row(exit_decision)

    assert "skip_negative_funding" in ledger
    assert "paper_open" in ledger
    assert "paper_exit" in ledger
    assert "skip_kill_switch" in ledger
    assert entry_row["expected_funding_apr"] == 0.22
    assert entry_row["fees_usd"] is not None
    assert entry_row["slippage_usd"] is not None
    assert entry_row["basis"] == 100.0
    assert entry_row["margin_buffer"] == 0.35
    assert "threshold_met" in entry_row["risk_checks"]
    assert exit_row["exit_reason"] == "funding_flip"


def test_carry_reconciliation_mismatch_blocks_live_progression():
    engine = PaperCarryEngine(min_net_apr=0.15)
    engine.process_input(_carry_input(annualized_rate=0.22))

    report = reconcile_carry_state(state=engine.state, ledger_decisions=engine.state.decisions, venue_positions={})
    rendered = render_carry_reconciliation_report(report)

    assert report.ok is False
    assert report.blocks_live is True
    assert report.mismatches[0].name == "venue_missing_position"
    assert "venue_missing_position" in rendered


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
