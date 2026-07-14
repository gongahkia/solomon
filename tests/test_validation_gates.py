from __future__ import annotations

from datetime import UTC, datetime, timedelta

from stonks_cli.research.validation_gates import (
    CAPTURE_GATE,
    assess_gate,
    record_capture_health,
    record_capture_probe,
    render_gate_report,
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
    assert "capture_dropped_messages_present" in assessment.blockers
    assert "capture_missing_clean_linux_live_completion" in assessment.blockers


def test_capture_gate_can_pass_after_clean_linux_live_completion(tmp_path):
    state = record_capture_health(
        state_dir=tmp_path,
        reset=True,
        now=NOW,
        capture_payload={
            "source": "live_capture",
            "runtime": {"os": "Linux"},
            "health": {"malformed_messages": 0, "dropped_messages": 0},
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


def test_capture_gate_rejects_non_linux_completion(tmp_path):
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

    assert "capture_missing_clean_linux_live_completion" in assessment.blockers


def test_capture_report_renders_current_gate_state(tmp_path):
    state = record_capture_probe(state_dir=tmp_path, reset=True, now=NOW)

    report = render_gate_report(state, now=NOW)

    assert "# 7-day Hyperliquid connector clean capture" in report
    assert "elapsed_days_below_target" in report
