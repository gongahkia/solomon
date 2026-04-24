from __future__ import annotations

import sys
import types


def _import_commands():
    blocking = types.ModuleType("apscheduler.schedulers.blocking")
    blocking.BlockingScheduler = object
    background = types.ModuleType("apscheduler.schedulers.background")
    background.BackgroundScheduler = object
    cron = types.ModuleType("apscheduler.triggers.cron")

    class _CronTrigger:
        @classmethod
        def from_crontab(cls, expr):
            return expr

    cron.CronTrigger = _CronTrigger
    sys.modules.setdefault("apscheduler", types.ModuleType("apscheduler"))
    sys.modules.setdefault("apscheduler.schedulers", types.ModuleType("apscheduler.schedulers"))
    sys.modules["apscheduler.schedulers.blocking"] = blocking
    sys.modules["apscheduler.schedulers.background"] = background
    sys.modules.setdefault("apscheduler.triggers", types.ModuleType("apscheduler.triggers"))
    sys.modules["apscheduler.triggers.cron"] = cron

    from stonks_cli import commands

    return commands


def test_polymarket_rust_status_reports_workspace(monkeypatch, tmp_path):
    commands = _import_commands()

    workspace = tmp_path / "rust"
    (workspace / "hotpath").mkdir(parents=True)
    (workspace / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
    (workspace / "hotpath" / "Cargo.toml").write_text("[package]\nname='x'\nversion='0.1.0'\n", encoding="utf-8")
    (workspace / "target" / "debug").mkdir(parents=True)
    (workspace / "target" / "debug" / "stonks-polymarket-hotpath").write_text("", encoding="utf-8")

    monkeypatch.setattr(commands, "_rust_workspace_root", lambda: workspace)
    monkeypatch.setattr(commands.shutil, "which", lambda name: f"/usr/bin/{name}")

    status = commands.do_polymarket_rust_status()

    assert status["workspace_exists"] is True
    assert status["binary_exists"] is True
    assert status["cargo_present"] is True


def test_polymarket_rust_ping_uses_binary(monkeypatch, tmp_path):
    commands = _import_commands()

    workspace = tmp_path / "rust"
    binary = workspace / "target" / "debug" / "stonks-polymarket-hotpath"
    binary.parent.mkdir(parents=True)
    binary.write_text("", encoding="utf-8")
    monkeypatch.setattr(commands, "_rust_workspace_root", lambda: workspace)

    class _Completed:
        returncode = 0
        stdout = "PONG\n"
        stderr = ""

    def _run(cmd, capture_output, text, check, cwd=None):
        assert cmd == [str(binary), "ping"]
        return _Completed()

    monkeypatch.setattr(commands.subprocess, "run", _run)

    result = commands.do_polymarket_rust_ping()

    assert result["returncode"] == 0
    assert result["stdout"] == "PONG"


def test_polymarket_rust_test_shells_out(monkeypatch, tmp_path):
    commands = _import_commands()

    workspace = tmp_path / "rust"
    workspace.mkdir()
    monkeypatch.setattr(commands, "_rust_workspace_root", lambda: workspace)

    class _Completed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _run(cmd, cwd, capture_output, text, check):
        assert cmd == ["cargo", "test"]
        assert cwd == workspace
        return _Completed()

    monkeypatch.setattr(commands.subprocess, "run", _run)

    result = commands.do_polymarket_rust_test()

    assert result["returncode"] == 0
    assert result["stdout"] == "ok"
