from __future__ import annotations

import sys
import types

from stonks_cli.config import AppConfig, PolymarketConfig


def _import_commands(monkeypatch):
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
    monkeypatch.setitem(sys.modules, "apscheduler", types.ModuleType("apscheduler"))
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers", types.ModuleType("apscheduler.schedulers"))
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers.blocking", blocking)
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers.background", background)
    monkeypatch.setitem(sys.modules, "apscheduler.triggers", types.ModuleType("apscheduler.triggers"))
    monkeypatch.setitem(sys.modules, "apscheduler.triggers.cron", cron)

    from stonks_cli import commands

    return commands


def test_runtime_loop_routes_to_rust_control(monkeypatch):
    commands = _import_commands(monkeypatch)
    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=False, rust_hotpath_enabled=True))
    monkeypatch.setattr(commands, "load_config", lambda: cfg)
    calls: list[tuple[str, dict[str, object] | None]] = []

    def _control(op: str, *, args=None):
        calls.append((op, args))
        return {"cycles": args["cycles"], "source": "rust"}

    monkeypatch.setattr(commands, "_polymarket_control", _control)

    result = commands.do_polymarket_runtime_loop(
        limit=1,
        cycles=2,
        sleep_seconds=0.0,
        market_messages=3,
        user_messages=4,
    )

    assert result == {"cycles": 2, "source": "rust"}
    assert calls == [
        (
            "runtime_loop",
            {
                "limit": 1,
                "cycles": 2,
                "sleep_seconds": 0.0,
                "market_messages": 3,
                "user_messages": 4,
            },
        )
    ]


def test_runtime_once_and_scan_route_to_rust_control(monkeypatch):
    commands = _import_commands(monkeypatch)
    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=True, scanner_limit=25))
    monkeypatch.setattr(commands, "load_config", lambda: cfg)
    calls: list[tuple[str, dict[str, object] | None]] = []

    def _control(op: str, *, args=None):
        calls.append((op, args))
        return [{"token_id": "YES1"}] if op == "scan" else {"status": {"state": "idle"}}

    monkeypatch.setattr(commands, "_polymarket_control", _control)

    scan = commands.do_polymarket_scan()
    once = commands.do_polymarket_runtime_once()

    assert scan == [{"token_id": "YES1"}]
    assert once == {"status": {"state": "idle"}}
    assert calls == [
        ("scan", {"limit": 25, "include_filtered": False}),
        ("runtime_once", {"limit": 25}),
    ]
