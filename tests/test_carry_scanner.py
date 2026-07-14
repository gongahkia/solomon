from __future__ import annotations

import json
from datetime import UTC, datetime

from typer.testing import CliRunner

from stonks_cli.carry.carry_scanner import (
    CarryCostAssumptions,
    calculate_carry_scan_row,
    scan_hyperliquid_carry,
)
from stonks_cli.cli import app
from stonks_cli.config import AppConfig
from stonks_cli.research.hyperliquid import HyperliquidCarryInput
from stonks_cli.research.models import BasisSnapshot, CarryQuote, FundingSnapshot, Venue


def test_carry_scanner_ranks_positive_opportunity():
    row = calculate_carry_scan_row(
        _carry_input(annualized_rate=0.22),
        min_net_apr=0.15,
        assumptions=CarryCostAssumptions(
            fee_bps=10,
            slippage_bps=10,
            rebalance_bps=10,
            borrow_bps=0,
            volatility_buffer_bps=20,
        ),
        now=datetime(2026, 7, 2, 0, 0, 10, tzinfo=UTC),
    )

    assert row.status == "candidate"
    assert row.threshold_met is True
    assert row.opportunity.gross_apr == 0.22
    assert round(row.opportunity.net_apr, 3) == 0.215
    assert row.opportunity.direction == "long_spot_short_perp"
    assert row.opportunity.required_fields_missing == []


def test_carry_scanner_skips_below_threshold_opportunity():
    row = calculate_carry_scan_row(
        _carry_input(annualized_rate=0.151),
        min_net_apr=0.15,
        assumptions=CarryCostAssumptions(volatility_buffer_bps=25),
        now=datetime(2026, 7, 2, 0, 0, 10, tzinfo=UTC),
    )

    assert row.status == "below_threshold"
    assert row.threshold_met is False
    assert row.opportunity.net_apr < 0.15


def test_carry_scanner_blocks_missing_fields_without_estimating():
    row = calculate_carry_scan_row(
        _carry_input(annualized_rate=0.22, spot_mid=None, basis=None),
        min_net_apr=0.15,
        now=datetime(2026, 7, 2, 0, 0, 10, tzinfo=UTC),
    )

    assert row.status == "blocked_missing_inputs"
    assert row.threshold_met is False
    assert "quote.spot_mid" in row.opportunity.required_fields_missing
    assert "basis" in row.opportunity.required_fields_missing
    assert row.opportunity.net_apr == 0.0


def test_scan_hyperliquid_carry_uses_config_min_net_apr():
    cfg = AppConfig()
    cfg.carry.min_net_apr = 0.20

    rows = scan_hyperliquid_carry(
        cfg=cfg,
        inputs=[_carry_input(annualized_rate=0.19)],
        now=datetime(2026, 7, 2, 0, 0, 10, tzinfo=UTC),
    )

    assert rows[0].min_net_apr == 0.20
    assert rows[0].status == "below_threshold"


def test_carry_scan_cli_outputs_json_from_fixture(tmp_path, monkeypatch):
    fixture = tmp_path / "carry-inputs.json"
    cfg_path = tmp_path / "config.json"
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))
    fixture.write_text(json.dumps({"inputs": [_carry_input(annualized_rate=0.22).to_dict()]}), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["scan-carry", "--fixture", str(fixture), "--json", "--now", "2026-07-02T00:00:10Z"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["paper"] is True
    assert payload["venue"] == "hyperliquid"
    assert payload["rows"][0]["status"] == "candidate"
    assert payload["rows"][0]["opportunity"]["gross_apr"] == 0.22
    assert "cost_assumptions" in payload["rows"][0]
    assert "source_health" in payload["rows"][0]


def test_carry_scan_cli_outputs_table_from_fixture(tmp_path, monkeypatch):
    fixture = tmp_path / "carry-inputs.json"
    cfg_path = tmp_path / "config.json"
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))
    fixture.write_text(json.dumps({"inputs": [_carry_input(annualized_rate=0.22).to_dict()]}), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["scan-carry", "--fixture", str(fixture), "--now", "2026-07-02T00:00:10Z"],
    )

    assert result.exit_code == 0
    assert "Carry scan" in result.output
    assert "BTC" in result.output
    assert "candidate" in result.output


def _carry_input(
    *,
    annualized_rate: float,
    spot_mid: float | None = 100000.0,
    basis: BasisSnapshot | None | bool = True,
) -> HyperliquidCarryInput:
    quote = CarryQuote(
        venue=Venue.HYPERLIQUID,
        asset="BTC",
        spot_mid=spot_mid,
        perp_mid=100100.0,
        oracle_mid=100050.0,
        mark_mid=100090.0,
        timestamp="2026-07-02T00:00:00Z",
        source_health="ok",
    )
    resolved_basis = (
        BasisSnapshot(
            asset="BTC",
            spot_mid=100000.0,
            perp_mid=100100.0,
            basis_abs=100.0,
            basis_pct=0.001,
            annualized_basis=0.0,
            timestamp="2026-07-02T00:00:00Z",
        )
        if basis is True
        else basis
    )
    return HyperliquidCarryInput(
        asset="BTC",
        quote=quote,
        funding=FundingSnapshot(
            asset="BTC",
            venue=Venue.HYPERLIQUID,
            hourly_rate=annualized_rate / (24 * 365),
            annualized_rate=annualized_rate,
            next_funding_time=None,
            premium_index=0.001,
            timestamp="2026-07-02T00:00:00Z",
        ),
        basis=resolved_basis,
        metadata={"perp": {"name": "BTC"}, "spot": {"name": "BTC/USDC"}},
        source_health={"all_mids": "ok", "perp_context": "ok", "spot_context": "ok"},
    )
