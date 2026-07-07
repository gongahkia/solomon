from __future__ import annotations

from datetime import UTC, datetime, timedelta

from stonks_cli.whalemirror.validation_gates import (
    CAPTURE_GATE,
    LIVE_GATE,
    PAPER_GATE,
    assess_gate,
    latency_report,
    record_capture_health,
    record_capture_probe,
    record_live_evidence,
    record_live_probe,
    record_paper_evidence,
    record_paper_probe,
    render_gate_report,
    scale_gate_report,
    slippage_report,
)

NOW = datetime(2026, 5, 17, 0, 0, tzinfo=UTC)


def test_capture_gate_probe_is_restartable_and_records_health(tmp_path):
    state = record_capture_probe(state_dir=tmp_path, capture_out_dir=tmp_path / "captures", reset=True, now=NOW)
    state = record_capture_probe(state_dir=tmp_path, capture_out_dir=tmp_path / "captures", now=NOW + timedelta(hours=1))
    assessment = assess_gate(state, now=NOW + timedelta(hours=1))

    assert state.gate_id == CAPTURE_GATE
    assert len(state.evidence) == 2
    assert state.evidence[-1].payload["health"]["decoded_trades"] == 5
    assert state.evidence[-1].payload["capture_out_path"]
    assert "elapsed_days_below_target" in assessment.blockers[0]
    assert "capture_dropped_messages_present" in assessment.blockers
    assert "capture_missing_clean_linux_live_completion" in assessment.blockers


def test_capture_gate_can_pass_after_clean_linux_live_completion(tmp_path):
    state = record_capture_health(
        state_dir=tmp_path,
        reset=True,
        now=NOW,
        capture_payload={
            "source": "live_capture",
            "raw_out_path": "/var/lib/stonks-cli/whalemirror-gates/captures/raw.jsonl",
            "capture_out_path": "/var/lib/stonks-cli/whalemirror-gates/captures/trades.jsonl",
            "health_out_path": "/var/lib/stonks-cli/whalemirror-gates/reports/health.json",
            "runtime": {"os": "Linux"},
            "health": {
                "messages_received": 1000,
                "decoded_events": 1000,
                "decoded_trades": 250,
                "malformed_messages": 0,
                "dropped_messages": 0,
                "reconnects": 1,
            },
            "decoded_event_count": 1000,
            "decoded_trade_count": 250,
            "final_status": "clean_capture",
        },
    )

    assessment = assess_gate(state, now=NOW + timedelta(days=7, minutes=1))

    assert assessment.status == "passed"
    assert assessment.blockers == []


def test_capture_gate_marks_stale_running_live_health(tmp_path):
    state = record_capture_health(
        state_dir=tmp_path,
        reset=True,
        now=NOW,
        capture_payload={
            "source": "live_capture",
            "runtime": {"os": "Linux"},
            "health": {"malformed_messages": 0, "dropped_messages": 0},
            "final_status": "running",
        },
    )

    assessment = assess_gate(state, now=NOW + timedelta(minutes=16))

    assert assessment.status == "stale"
    assert any(blocker.startswith("capture_health_stale") for blocker in assessment.blockers)
    assert "capture_missing_clean_linux_live_completion" in assessment.blockers


def test_capture_gate_blocks_non_linux_live_completion(tmp_path):
    state = record_capture_health(
        state_dir=tmp_path,
        reset=True,
        now=NOW,
        capture_payload={
            "source": "live_capture",
            "runtime": {"os": "Darwin"},
            "health": {"malformed_messages": 0, "dropped_messages": 0},
            "final_status": "clean_capture",
        },
    )

    assessment = assess_gate(state, now=NOW + timedelta(days=8))

    assert "capture_not_run_on_linux_operator_host" in assessment.blockers


def test_paper_gate_probe_records_tearsheet_and_risk_controls(tmp_path):
    state = record_paper_probe(state_dir=tmp_path, reset=True, now=NOW)
    assessment = assess_gate(state, now=NOW + timedelta(days=29))

    payload = state.evidence[-1].payload
    assert state.gate_id == PAPER_GATE
    assert payload["tearsheet"]["wins"] == 1
    assert payload["tearsheet"]["losses"] == 1
    assert "paper_mirror_open" in payload["risk_controls"]
    assert "stop_loss" in payload["risk_controls"]
    assert "cooldown" in payload["risk_controls"]
    assert payload["source"] == "fixture"
    assert assessment.status == "running"
    assert any("elapsed_days_below_target" in blocker for blocker in assessment.blockers)
    assert "paper_missing_linux_live_paper_evidence" in assessment.blockers


def test_paper_gate_can_pass_after_completed_linux_live_evidence(tmp_path):
    state = record_paper_evidence(
        state_dir=tmp_path,
        reset=True,
        now=NOW,
        paper_payload=_live_paper_payload(),
    )

    assessment = assess_gate(state, now=NOW + timedelta(days=30, minutes=1))

    assert assessment.status == "passed"
    assert assessment.blockers == []


def test_paper_gate_blocks_incomplete_or_non_linux_live_evidence(tmp_path):
    payload = _live_paper_payload()
    payload["runtime"] = {"os": "Darwin"}
    payload["final_status"] = "running"
    payload["selected_wallets"] = payload["selected_wallets"][:4]
    payload["tearsheet"]["risk_cap_skips"] = 0

    state = record_paper_evidence(state_dir=tmp_path, reset=True, now=NOW, paper_payload=payload)
    assessment = assess_gate(state, now=NOW + timedelta(days=31))

    assert "paper_live_run_not_completed" in assessment.blockers
    assert "paper_not_run_on_linux_operator_host" in assessment.blockers
    assert "paper_selected_wallets_below_top5" in assessment.blockers
    assert "paper_missing_risk_cap_skip_evidence" in assessment.blockers


def test_live_gate_probe_reports_latency_slippage_and_scale_gate(tmp_path):
    state = record_live_probe(state_dir=tmp_path, reset=True, now=NOW)
    assessment = assess_gate(state, now=NOW + timedelta(days=1))

    payload = state.evidence[-1].payload
    assert state.gate_id == LIVE_GATE
    assert payload["latency_report"]["p50_ms"] == 710
    assert payload["source"] == "fixture"
    assert payload["latency_report"]["p95_ms"] == 926
    assert payload["latency_report"]["failure_count"] == 1
    assert payload["slippage_report"]["sample_count"] == 2
    assert payload["scale_gate"]["effective_max_live_order_notional_usd"] == 50
    assert payload["scale_gate"]["auto_raise_blocked"] is True
    assert assessment.status == "running"
    assert any("elapsed_days_below_target" in blocker for blocker in assessment.blockers)
    assert "live_missing_linux_live_validation_evidence" in assessment.blockers


def test_live_gate_can_pass_after_completed_linux_live_evidence(tmp_path):
    state = record_live_evidence(
        state_dir=tmp_path,
        reset=True,
        now=NOW,
        live_payload=_live_validation_payload(),
    )

    assessment = assess_gate(state, now=NOW + timedelta(days=60, minutes=1))

    assert assessment.status == "passed"
    assert assessment.blockers == []


def test_live_gate_blocks_incomplete_or_unsafe_live_evidence(tmp_path):
    payload = _live_validation_payload()
    payload["runtime"] = {"os": "Darwin"}
    payload["final_status"] = "running"
    payload["max_live_order_notional_usd"] = 75
    payload["latency_report"]["p95_ms"] = 850
    payload["latency_reframe_path"] = ""
    payload["scale_gate"]["auto_raise_blocked"] = False
    payload["scale_gate"]["scale_gate_satisfied"] = False

    state = record_live_evidence(state_dir=tmp_path, reset=True, now=NOW, live_payload=payload)
    assessment = assess_gate(state, now=NOW + timedelta(days=61))

    assert "live_validation_not_completed" in assessment.blockers
    assert "live_not_run_on_linux_operator_host" in assessment.blockers
    assert "live_notional_cap_above_50_usd" in assessment.blockers
    assert "live_latency_reframe_missing" in assessment.blockers
    assert "live_scale_gate_guard_not_proven" in assessment.blockers


def test_gate_report_renders_blockers_and_evidence(tmp_path):
    state = record_paper_probe(state_dir=tmp_path, reset=True, now=NOW)

    report = render_gate_report(state, now=NOW)

    assert "# 30-day top-5 Hyperliquid paper mirror gate" in report
    assert "paper_tearsheet" in report
    assert "elapsed_days_below_target" in report


def test_metric_helpers_are_deterministic():
    latency = latency_report(
        [
            {"detected_at_ms": 0, "submitted_at_ms": 100, "status": "ok"},
            {"detected_at_ms": 0, "submitted_at_ms": 300, "status": "ok"},
        ]
    )
    slippage = slippage_report([{"paper_px": 100, "live_px": 101, "side": "buy"}])
    scale = scale_gate_report(
        {
            "current_max_live_order_notional_usd": 50,
            "requested_max_live_order_notional_usd": 200,
            "green_weeks": 6,
            "required_green_weeks": 7,
        }
    )

    assert latency["p50_ms"] == 200
    assert latency["p95_ms"] == 290
    assert slippage["avg_slippage_bps"] == 100
    assert scale["effective_max_live_order_notional_usd"] == 50
    assert scale["auto_raise_blocked"] is True


def _live_paper_payload():
    return {
        "source": "live_paper",
        "final_status": "completed",
        "runtime": {"os": "Linux"},
        "selected_wallets": [
            "0x0000000000000000000000000000000000000001",
            "0x0000000000000000000000000000000000000002",
            "0x0000000000000000000000000000000000000003",
            "0x0000000000000000000000000000000000000004",
            "0x0000000000000000000000000000000000000005",
        ],
        "ledger_path": "/var/lib/stonks-cli/whalemirror-gates/reports/paper-ledger.md",
        "journal_path": "/var/lib/stonks-cli/whalemirror-gates/reports/paper-journal.jsonl",
        "report_path": "/var/lib/stonks-cli/whalemirror-gates/reports/paper-gate.md",
        "risk_controls": ["paper_mirror_open", "risk_cap", "stop_loss", "cooldown"],
        "tearsheet": {
            "closed_trades": 2,
            "open_positions": 0,
            "wins": 1,
            "losses": 1,
            "realized_pnl_usd": -1.5,
            "expectancy_usd": -0.75,
            "sharpe": -0.2,
            "max_drawdown_usd": 5.0,
            "risk_cap_skips": 1,
            "stop_loss_exits": 1,
            "cooldown_blocks": 1,
            "skipped_trades": 2,
        },
    }


def _live_validation_payload():
    return {
        "source": "live_armed",
        "final_status": "completed",
        "runtime": {"os": "Linux"},
        "max_live_order_notional_usd": 49.0,
        "latency_report_path": "/var/lib/stonks-cli/whalemirror-gates/reports/live-latency.md",
        "slippage_report_path": "/var/lib/stonks-cli/whalemirror-gates/reports/live-vs-paper-slippage.md",
        "ledger_path": "/var/lib/stonks-cli/whalemirror-gates/reports/live-ledger.md",
        "latency_report": {
            "sample_count": 12,
            "p50_ms": 410.0,
            "p95_ms": 790.0,
            "failure_count": 1,
            "drop_context": ["ws_reconnect"],
        },
        "slippage_report": {
            "sample_count": 12,
            "avg_slippage_bps": 3.2,
            "max_slippage_bps": 9.1,
        },
        "scale_gate": {
            "current_max_live_order_notional_usd": 49.0,
            "requested_max_live_order_notional_usd": 100.0,
            "effective_max_live_order_notional_usd": 49.0,
            "green_weeks": 6,
            "required_green_weeks": 7,
            "scale_gate_satisfied": False,
            "auto_raise_blocked": True,
        },
    }
