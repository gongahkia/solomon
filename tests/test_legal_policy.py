from __future__ import annotations

import json

from typer.testing import CliRunner

from stonks_cli.cli import app
from stonks_cli.config import AppConfig
from stonks_cli.legal_policy import evaluate_legal_policy


def test_legal_policy_blocks_sg_restricted_venues_and_strategy_classes():
    cfg = AppConfig()

    venue_check = evaluate_legal_policy(cfg, venue_id="polymarket", strategy_class="carry_funding_basis")
    strategy_check = evaluate_legal_policy(cfg, venue_id="hyperliquid", strategy_class="prediction-market")

    assert venue_check.blockers == ["legal_policy_blocked_venue:polymarket"]
    assert strategy_check.blockers == ["legal_policy_blocked_strategy:prediction_market"]


def test_legal_policy_can_be_disabled_for_non_sg_context():
    cfg = AppConfig.model_validate({"legal_policy": {"sg_resident": False}})

    check = evaluate_legal_policy(cfg, venue_id="polymarket", strategy_class="prediction_market")

    assert check.ok is True
    assert check.blockers == []


def test_carry_scan_blocks_bybit_before_scanner_execution(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    result = CliRunner().invoke(app, ["carry", "scan", "--venue", "bybit", "--json"])

    assert result.exit_code != 0
    assert "legal_policy_blocked_venue:bybit" in result.output
