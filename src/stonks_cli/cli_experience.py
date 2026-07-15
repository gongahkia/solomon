from __future__ import annotations

import json
import os
import shutil
import socket
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from stonks_cli.config import AppConfig, config_path, load_config
from stonks_cli.paths import default_cache_dir, default_config_path, default_state_dir


@dataclass(frozen=True)
class ManagedPaths:
    config: Path
    state: Path
    cache: Path

    def to_dict(self) -> dict[str, str]:
        return {"cache": str(self.cache), "config": str(self.config), "state": str(self.state)}


def is_interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def managed_paths() -> ManagedPaths:
    return ManagedPaths(config=config_path(), state=default_state_dir(), cache=default_cache_dir())


def inspect_home() -> dict[str, Any]:
    paths = managed_paths()
    target = config_path()
    status: dict[str, Any] = {
        "actions": [
            "stonks-cli onboard",
            "stonks-cli settings",
            "stonks-cli doctor",
            "stonks-cli scan-carry --json",
            "stonks-cli run-carry-paper --duration-hours 0",
        ],
        "config": {
            "exists": target.exists(),
            "path": str(target),
            "uses_default_path": target == default_config_path(),
        },
        "paths": paths.to_dict(),
    }
    try:
        cfg = load_config(target)
    except Exception as error:
        status["config"]["valid"] = False
        status["config"]["error"] = str(error)
        status["safety"] = {"live_execution": "blocked"}
        return status
    status["config"]["valid"] = True
    status["integrations"] = _integration_status(cfg)
    status["readiness"] = _readiness_status(cfg)
    status["evidence"] = _evidence_status(paths.state)
    status["safety"] = {
        "carry_live_armed": cfg.carry.live_armed,
        "execution_mode": cfg.vnext.operator.execution_mode,
        "live_execution": "blocked",
        "paper_carry": cfg.carry.paper,
    }
    status["carry_gate"] = _carry_gate_status(paths.state)
    return status


def render_home(status: dict[str, Any], *, console: Console | None = None) -> None:
    console = console or Console()
    safety = status["safety"]
    summary = (
        f"Live execution: [bold red]{safety['live_execution']}[/]\n"
        f"Paper carry: {'[green]enabled[/]' if safety.get('paper_carry') else '[yellow]disabled[/]'}\n"
        f"Config: {'[green]valid[/]' if status['config'].get('valid') else '[red]needs attention[/]'}"
    )
    console.print(Panel(summary, title="stonks-cli", subtitle="paper-first research"))
    table = Table(title="Readiness")
    table.add_column("Area")
    table.add_column("Status")
    config = status["config"]
    table.add_row("Config", "ready" if config.get("valid") else f"error: {config.get('error', 'unknown')}")
    if "integrations" in status:
        for name, value in status["integrations"].items():
            table.add_row(name.replace("_", " ").title(), value)
    if "readiness" in status:
        for name, value in status["readiness"].items():
            table.add_row(name.replace("_", " ").title(), value["status"])
    if "evidence" in status:
        for name, value in status["evidence"].items():
            table.add_row(name.replace("_", " ").title(), value["status"])
    gate = status.get("carry_gate", {})
    table.add_row("30-day carry gate", gate.get("status", "not started"))
    console.print(table)
    console.print("[bold]Next[/]")
    for action in status["actions"]:
        console.print(f"  {action}")


def backup_config(path: Path) -> Path | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"config path is not a regular file: {path}")
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.bak.{suffix}")
    shutil.copy2(path, backup)
    return backup


def removable_paths(*, include_config: bool) -> list[Path]:
    paths = managed_paths()
    selected = [paths.cache]
    if include_config:
        selected.insert(0, paths.config)
        selected.append(paths.state)
    elif paths.state != paths.config.parent:
        selected.append(paths.state)
    elif paths.state.exists():
        selected.extend(
            path
            for path in paths.state.iterdir()
            if path != paths.config and not path.name.startswith(f"{paths.config.name}.bak.")
        )
    return selected


def remove_managed_paths(paths: list[Path]) -> list[Path]:
    removed: list[Path] = []
    for path in paths:
        if not path.exists():
            continue
        if path.is_symlink():
            raise ValueError(f"refusing to remove symlink: {path}")
        if path.is_dir():
            shutil.rmtree(path)
        elif path.is_file():
            path.unlink()
        else:
            raise ValueError(f"refusing to remove unsupported path: {path}")
        removed.append(path)
    return removed


def package_uninstall_guidance() -> str:
    return "Remove the package separately with your installer, for example: uv tool uninstall stonks-cli"


def _integration_status(cfg: AppConfig) -> dict[str, str]:
    return {
        "carry": "paper-only" if cfg.carry.paper else "disabled",
        "crypto_research": "enabled" if cfg.vnext.research.enabled else "not configured",
        "moomoo": "read-only enabled" if cfg.vnext.moomoo.enabled else "not configured",
        "operator_reports": "enabled" if cfg.vnext.operator.telegram.enabled else "not configured",
    }


def _readiness_status(cfg: AppConfig) -> dict[str, dict[str, str]]:
    return {
        "moomoo_connection": _moomoo_readiness(cfg),
        "carry_alerts": _carry_alert_readiness(cfg),
        "operator_telegram": _operator_telegram_readiness(cfg),
    }


def _moomoo_readiness(cfg: AppConfig) -> dict[str, str]:
    moomoo = cfg.vnext.moomoo
    if not moomoo.enabled:
        return {"status": "not configured", "detail": "read-only OpenD integration is disabled"}
    try:
        with socket.create_connection((moomoo.host, moomoo.port), timeout=min(moomoo.connection_timeout_seconds, 0.5)):
            pass
    except OSError as error:
        return {"status": "configured; unreachable", "detail": f"{moomoo.host}:{moomoo.port}: {error}"}
    return {"status": "read-only reachable", "detail": f"{moomoo.host}:{moomoo.port}"}


def _carry_alert_readiness(cfg: AppConfig) -> dict[str, str]:
    carry = cfg.carry
    if carry.alert_sink == "disabled":
        return {"status": "disabled", "detail": "no carry alert delivery configured"}
    names = (
        (carry.telegram_bot_token_env, carry.telegram_chat_id_env)
        if carry.alert_sink == "telegram"
        else (carry.email_smtp_url_env, carry.email_to_env)
    )
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        return {"status": "configured; credentials missing", "detail": ", ".join(missing)}
    return {"status": f"{carry.alert_sink} credentials ready", "detail": "delivery is not attempted by this check"}


def _operator_telegram_readiness(cfg: AppConfig) -> dict[str, str]:
    telegram = cfg.vnext.operator.telegram
    if not telegram.enabled:
        return {"status": "not configured", "detail": "operator Telegram reports are disabled"}
    missing = [name for name in (telegram.bot_token_env, telegram.chat_id_env) if not os.getenv(name)]
    if missing:
        return {"status": "configured; credentials missing", "detail": ", ".join(missing)}
    return {"status": "credentials ready", "detail": "delivery is not attempted by this check"}


def _evidence_status(state_dir: Path) -> dict[str, dict[str, str]]:
    return {
        "capture_validation": _capture_evidence_status(state_dir),
        "carry_paper_artifacts": _carry_gate_status(state_dir),
    }


def _capture_evidence_status(state_dir: Path) -> dict[str, str]:
    path = state_dir / "validation-gates" / "capture-7d.json"
    if not path.exists():
        return {
            "status": "not started",
            "detail": "no persisted connector evidence",
            "remediation": "run a Linux live capture; fixtures are not gate evidence",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        evidence = payload.get("evidence")
        if not isinstance(evidence, list):
            raise ValueError("evidence is invalid")
        live = [item for item in evidence if str((item.get("payload") or {}).get("source")) == "live_capture"]
        updated_at = str(payload.get("updated_at_utc") or "unknown")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {
            "status": "invalid",
            "detail": str(error),
            "remediation": "recreate validation-gates/capture-7d.json from a clean capture",
        }
    if not live:
        return {
            "status": "synthetic or incomplete",
            "detail": f"{len(evidence)} record(s); no live capture; updated {updated_at}",
            "remediation": "record a clean Linux live capture before relying on this gate",
        }
    return {
        "status": "live evidence recorded",
        "detail": f"{len(live)} live record(s); updated {updated_at}",
        "remediation": "inspect capture-gate status for duration and freshness blockers",
    }


def _carry_gate_status(state_dir: Path) -> dict[str, str]:
    candidates = (
        state_dir / "carry-paper" / "latest-report.md",
        state_dir / "carry-paper" / "report.md",
        state_dir / "carry-paper" / "carry-paper-state.json",
    )
    artifact = next((path for path in candidates if path.exists()), None)
    if artifact is None:
        return {
            "status": "not started",
            "detail": "no managed paper-carry artifact",
            "remediation": "run stonks-cli run-carry-paper with a managed --state-dir",
        }
    age_seconds = max(0.0, datetime.now(UTC).timestamp() - artifact.stat().st_mtime)
    freshness = "fresh" if age_seconds <= 900 else "stale"
    return {
        "status": f"artifacts present; {freshness}",
        "detail": f"{artifact}; age {age_seconds:.0f}s",
        "remediation": "run another paper cycle before using stale artifacts" if freshness == "stale" else "continue the paper observation window",
    }
