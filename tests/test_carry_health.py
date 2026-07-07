from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from typer.testing import CliRunner

from stonks_cli.cli import app
from stonks_cli.config import AppConfig
from stonks_cli.whalemirror.carry_health import build_carry_health_report


def test_carry_health_report_covers_pi_domains(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    ledger = state_dir / "ledger.md"
    heartbeat = state_dir / "carry-stream-heartbeat.json"
    ledger.write_text("# CarryMirror Audit Ledger\n", encoding="utf-8")
    heartbeat.write_text(json.dumps({"timestamp": "2026-07-02T00:00:00Z"}), encoding="utf-8")

    report = build_carry_health_report(
        cfg=AppConfig(),
        state_dir=state_dir,
        ledger_path=ledger,
        now=datetime(2026, 7, 2, tzinfo=UTC),
        skip_network=True,
    )

    assert {check.name for check in report.checks} == {
        "alerts",
        "host",
        "ledger",
        "network",
        "ram",
        "storage",
        "stream",
        "time_sync",
        "venue_api",
    }
    assert report.status == "warn"


def test_carry_health_fails_on_stale_stream_and_reconciliation_mismatch(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    ledger = state_dir / "ledger.md"
    heartbeat = state_dir / "carry-stream-heartbeat.json"
    reconciliation = state_dir / "carry-reconciliation.md"
    ledger.write_text("# CarryMirror Audit Ledger\n", encoding="utf-8")
    heartbeat.write_text(json.dumps({"timestamp": "2026-07-01T23:00:00Z"}), encoding="utf-8")
    reconciliation.write_text("- Blocks live progression: true\n", encoding="utf-8")

    report = build_carry_health_report(
        cfg=AppConfig(),
        state_dir=state_dir,
        ledger_path=ledger,
        now=datetime(2026, 7, 2, tzinfo=UTC),
        skip_network=True,
        max_stream_age_seconds=60,
    )

    checks = {check.name: check for check in report.checks}
    assert report.status == "fail"
    assert checks["stream"].status == "fail"
    assert checks["ledger"].status == "fail"


def test_carry_health_cli_outputs_json(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    ledger = state_dir / "ledger.md"
    heartbeat = state_dir / "carry-stream-heartbeat.json"
    cfg_path.write_text(json.dumps({"carrymirror": {"alert_sink": "disabled"}}), encoding="utf-8")
    ledger.write_text("# CarryMirror Audit Ledger\n", encoding="utf-8")
    heartbeat.write_text(json.dumps({"timestamp": datetime.now(UTC).isoformat()}), encoding="utf-8")
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    result = CliRunner().invoke(
        app,
        [
            "carry",
            "health",
            "--state-dir",
            str(state_dir),
            "--ledger",
            str(ledger),
            "--stream-heartbeat",
            str(heartbeat),
            "--skip-network",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "warn"
    assert any(check["name"] == "alerts" for check in payload["checks"])


def test_carry_health_alerts_pass_with_required_telegram_env(tmp_path, monkeypatch):
    cfg = AppConfig.model_validate({"carrymirror": {"alert_sink": "telegram"}})
    monkeypatch.setenv("STONKS_CLI_CARRY_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("STONKS_CLI_CARRY_TELEGRAM_CHAT_ID", "chat")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    ledger = state_dir / "ledger.md"
    heartbeat = state_dir / "carry-stream-heartbeat.json"
    ledger.write_text("# CarryMirror Audit Ledger\n", encoding="utf-8")
    heartbeat.write_text(json.dumps({"timestamp": (datetime(2026, 7, 2, tzinfo=UTC) - timedelta(seconds=1)).isoformat()}), encoding="utf-8")

    report = build_carry_health_report(
        cfg=cfg,
        state_dir=state_dir,
        ledger_path=ledger,
        now=datetime(2026, 7, 2, tzinfo=UTC),
        skip_network=True,
    )

    checks = {check.name: check for check in report.checks}
    assert checks["alerts"].status == "ok"
