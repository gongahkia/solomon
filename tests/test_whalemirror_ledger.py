from __future__ import annotations

from pathlib import Path

from stonks_cli.whalemirror.ledger import (
    DEFAULT_REPLAY_FIXTURE,
    build_tearsheet,
    load_replay_fixture,
    render_decision_ledger,
    render_tearsheet,
    write_fixture_artifacts,
)


def test_fixture_traces_signal_to_decision_to_outcome():
    traces = load_replay_fixture(DEFAULT_REPLAY_FIXTURE)

    assert len(traces) == 2
    assert traces[0].observed_trade["trade_id"] == "hl-fixture-001"
    assert traces[0].execution_intent["source_trade_id"] == "hl-fixture-001"
    assert traces[0].decision["receipt"] == "paper:wm-001"
    assert traces[0].status == "win"


def test_tearsheet_reports_wins_losses_and_bias_adjusted_metrics():
    traces = load_replay_fixture(DEFAULT_REPLAY_FIXTURE)

    metrics = build_tearsheet(traces)

    assert metrics["wins"] == 1
    assert metrics["losses"] == 1
    assert metrics["expectancy_usd"] == 1.15
    assert metrics["survivorship_adjusted_pnl_usd"] == 1.0
    assert metrics["funding_adjusted_pnl_usd"] == 2.13
    assert metrics["avg_decay_hours"] == 6.25


def test_ledger_and_tearsheet_make_loss_as_visible_as_win():
    traces = load_replay_fixture(DEFAULT_REPLAY_FIXTURE)

    ledger = render_decision_ledger(traces)
    tearsheet = render_tearsheet(traces)

    assert "paper:wm-001" in ledger
    assert "paper:wm-002" in ledger
    assert "| Wins | 1 |" in ledger
    assert "| Losses | 1 |" in ledger
    assert "expectancy" in ledger.lower()
    assert "Sharpe" in ledger
    assert "survivorship-adjusted PnL" in ledger
    assert "| Losses | 1 | -$5.10 | -$5.10 |" in tearsheet


def test_write_fixture_artifacts(tmp_path: Path):
    ledger = tmp_path / "decision-ledger.md"
    tearsheet = tmp_path / "tearsheet.md"

    result = write_fixture_artifacts(
        fixture_path=DEFAULT_REPLAY_FIXTURE,
        ledger_path=ledger,
        tearsheet_path=tearsheet,
    )

    assert result["decisions"] == 2
    assert ledger.read_text(encoding="utf-8").startswith("# Decision Ledger")
    assert "WhaleMirror Fixture Tearsheet" in tearsheet.read_text(encoding="utf-8")
