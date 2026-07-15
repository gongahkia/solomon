from __future__ import annotations

import json
import os

import pytest
import typer
from typer.testing import CliRunner

import stonks_cli.cli as cli
import stonks_cli.cli_experience as experience
from stonks_cli.cli import app


def test_home_json_reports_paper_safety(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg))

    result = CliRunner().invoke(app, ["home", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["safety"]["live_execution"] == "blocked"
    assert payload["safety"]["carry_live_armed"] is False
    assert "stonks-cli onboard" in payload["actions"]
    assert payload["readiness"]["moomoo_connection"]["status"] == "not configured"


def test_home_reports_configured_moomoo_and_missing_alert_credentials(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg))
    monkeypatch.setattr(
        experience.socket, "create_connection", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("refused"))
    )
    config = cli.load_config(cfg)
    config.vnext.enabled = True
    config.vnext.moomoo.enabled = True
    config.vnext.features.broker_data = True
    config.carry.alert_sink = "telegram"
    cli.save_config(config, cfg)

    payload = experience.inspect_home()

    assert payload["readiness"]["moomoo_connection"]["status"] == "configured; unreachable"
    assert payload["readiness"]["carry_alerts"]["status"] == "configured; credentials missing"


def test_home_labels_fixture_evidence_and_stale_artifacts(monkeypatch, tmp_path):
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    state = tmp_path / "home" / "state"
    gate = state / "validation-gates" / "capture-7d.json"
    gate.parent.mkdir(parents=True)
    gate.write_text(json.dumps({"updated_at_utc": "2026-01-01T00:00:00Z", "evidence": [{}]}), encoding="utf-8")
    report = state / "carry-paper" / "report.md"
    report.parent.mkdir(parents=True)
    report.write_text("paper", encoding="utf-8")
    os.utime(report, (0, 0))

    payload = experience.inspect_home()

    assert payload["evidence"]["capture_validation"]["status"] == "synthetic or incomplete"
    assert payload["evidence"]["carry_paper_artifacts"]["status"] == "artifacts present; stale"


def test_bare_cli_prints_help_when_not_interactive():
    result = CliRunner().invoke(app, [])

    assert result.exit_code == 0
    assert "Usage: root" in result.output or "Usage: stonks-cli" in result.output
    assert "onboard" in result.output


def test_doctor_smoke_is_local_and_synthetic(monkeypatch, tmp_path):
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "isolated"))

    result = CliRunner().invoke(app, ["doctor", "--smoke"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["synthetic"] is True
    assert payload["not_validation_evidence"] is True


def test_alert_preview_never_attempts_delivery(monkeypatch, tmp_path):
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(tmp_path / "config.json"))

    result = CliRunner().invoke(app, ["alert-preview", "--event", "stale_data"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["delivery"] == "not_attempted"
    assert payload["synthetic"] is True


def test_onboard_writes_paper_first_config(monkeypatch, tmp_path):
    target = tmp_path / "config.json"
    monkeypatch.setattr(cli, "is_interactive_terminal", lambda: True)
    answers = iter([True, True, True])
    monkeypatch.setattr(typer, "confirm", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr(typer, "prompt", lambda *_args, **_kwargs: "disabled")

    result = CliRunner().invoke(app, ["onboard", "--path", str(target)])

    assert result.exit_code == 0
    cfg = json.loads(target.read_text(encoding="utf-8"))
    assert cfg["carry"]["paper"] is True
    assert cfg["carry"]["live_armed"] is False
    assert cfg["vnext"]["enabled"] is True
    assert cfg["vnext"]["features"]["execution"] is False
    assert cfg["vnext"]["features"]["broker_data"] is True
    assert cfg["vnext"]["features"]["crypto_research"] is True
    assert cfg["vnext"]["features"]["operator_reports"] is True


def test_onboard_backs_up_existing_config(monkeypatch, tmp_path):
    target = tmp_path / "config.json"
    target.write_text('{"carry":{"min_net_apr":0.2}}', encoding="utf-8")
    monkeypatch.setattr(cli, "is_interactive_terminal", lambda: True)
    answers = iter([False, False, False])
    monkeypatch.setattr(typer, "confirm", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr(typer, "prompt", lambda *_args, **_kwargs: "disabled")

    result = CliRunner().invoke(app, ["onboard", "--path", str(target)])

    assert result.exit_code == 0
    assert list(tmp_path.glob("config.json.bak.*"))
    assert json.loads(target.read_text(encoding="utf-8"))["carry"]["min_net_apr"] == 0.2


def test_settings_rejects_execution_field(monkeypatch, tmp_path):
    target = tmp_path / "config.json"
    monkeypatch.setattr(cli, "is_interactive_terminal", lambda: True)
    answers = iter(["advanced", "carry.live_armed"])
    monkeypatch.setattr(typer, "prompt", lambda *_args, **_kwargs: next(answers))

    result = CliRunner().invoke(app, ["settings", "--path", str(target)])

    assert result.exit_code == 2
    assert "cannot enable execution" in result.output


def test_clean_paths_preserve_config_when_config_is_inside_state(monkeypatch, tmp_path):
    state = tmp_path / "state"
    config = state / "config.json"
    cache = tmp_path / "cache"
    config.parent.mkdir()
    config.write_text("{}", encoding="utf-8")
    generated = state / "events.jsonl"
    generated.write_text("event\n", encoding="utf-8")
    cache.mkdir()
    (cache / "data").write_text("cache\n", encoding="utf-8")
    monkeypatch.setattr(experience, "config_path", lambda: config)
    monkeypatch.setattr(experience, "default_state_dir", lambda: state)
    monkeypatch.setattr(experience, "default_cache_dir", lambda: cache)

    removed = experience.remove_managed_paths(experience.removable_paths(include_config=False))

    assert config.exists()
    assert generated in removed
    assert not generated.exists()
    assert not cache.exists()


def test_uninstall_paths_include_explicit_config(monkeypatch, tmp_path):
    config = tmp_path / "custom-config.json"
    monkeypatch.setattr(experience, "config_path", lambda: config)
    monkeypatch.setattr(experience, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(experience, "default_cache_dir", lambda: tmp_path / "cache")

    paths = experience.removable_paths(include_config=True)

    assert paths[0] == config


def test_remove_managed_paths_rejects_symlink(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        experience.remove_managed_paths([link])
