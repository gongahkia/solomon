from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from stonks_cli.config import AppConfig
from stonks_cli.paths import default_state_dir
from stonks_cli.polymarket.auth import authenticated_clob_client, load_api_credentials_from_env, private_key_from_env
from stonks_cli.polymarket.guards import active_halt_reason, live_trading_armed, load_guard_state
from stonks_cli.polymarket.lifecycle import live_orders_path
from stonks_cli.polymarket.rust_bridge import rust_session
from stonks_cli.polymarket.storage import runtime_state_path
from stonks_cli.polymarket.websocket import build_market_subscription, build_user_subscription


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: str
    detail: str


def run_preflight(cfg: AppConfig, *, deep_auth: bool = False) -> dict[str, Any]:
    checks: list[PreflightCheck] = []
    state_dir = default_state_dir()
    checks.append(_writable_check("state_dir", state_dir))
    checks.append(_writable_check("runtime_state_parent", runtime_state_path().parent))
    checks.append(_writable_check("live_orders_parent", live_orders_path().parent))

    halt_reason = active_halt_reason(load_guard_state())
    checks.append(
        PreflightCheck(
            name="guard_state",
            status="fail" if halt_reason else "pass",
            detail=halt_reason or "trading guards clear",
        )
    )

    checks.append(
        PreflightCheck(
            name="market_subscription",
            status="pass",
            detail=str(build_market_subscription(["sample-token"])),
        )
    )
    checks.append(_dependency_check("websockets", "websockets"))

    if cfg.polymarket.paper:
        checks.append(PreflightCheck(name="mode", status="warn", detail="paper mode enabled; live execution disabled"))
    else:
        checks.extend(_live_checks(cfg, deep_auth=deep_auth))

    overall = "pass"
    if any(check.status == "fail" for check in checks):
        overall = "fail"
    elif any(check.status == "warn" for check in checks):
        overall = "warn"
    return {
        "overall": overall,
        "paper": cfg.polymarket.paper,
        "deep_auth": deep_auth,
        "checks": [asdict(check) for check in checks],
    }


def _live_checks(cfg: AppConfig, *, deep_auth: bool) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []
    try:
        private_key_from_env(cfg)
    except Exception as e:
        checks.append(PreflightCheck(name="private_key", status="fail", detail=str(e)))
    else:
        checks.append(PreflightCheck(name="private_key", status="pass", detail="private key env present"))

    creds = load_api_credentials_from_env(cfg)
    if creds is None:
        checks.append(
            PreflightCheck(
                name="api_credentials_env",
                status="pass" if deep_auth else "warn",
                detail=(
                    "API creds not present in env; deep auth will attempt derivation"
                    if deep_auth
                    else "API creds not present in env; deep auth may derive them if supported"
                ),
            )
        )
    else:
        checks.append(PreflightCheck(name="api_credentials_env", status="pass", detail="API creds env present"))
        checks.append(
            PreflightCheck(
                name="user_subscription",
                status="pass",
                detail=str(build_user_subscription(auth=creds.as_dict())),
            )
        )

    checks.append(_dependency_check("py_clob_client_v2", "py_clob_client_v2"))
    checks.append(
        PreflightCheck(
            name="live_arm",
            status="pass" if live_trading_armed(cfg) or not cfg.polymarket.live_require_armed_env else "warn",
            detail=(
                f"{cfg.polymarket.live_armed_env} armed"
                if live_trading_armed(cfg)
                else f"set {cfg.polymarket.live_armed_env}=1 to allow live auto-trading"
            ),
        )
    )
    if cfg.polymarket.rust_hotpath_enabled:
        checks.extend(_rust_checks(cfg))

    if deep_auth:
        try:
            client, derived = authenticated_clob_client(cfg)
        except Exception as e:
            checks.append(PreflightCheck(name="authenticated_client", status="fail", detail=str(e)))
        else:
            checks.append(
                PreflightCheck(
                    name="authenticated_client",
                    status="pass",
                    detail=f"derived api key {derived.api_key[:8]}...",
                )
            )
            checks.append(
                PreflightCheck(
                    name="cancel_method",
                    status="pass" if _has_cancel_method(client) else "warn",
                    detail="supported cancel method found" if _has_cancel_method(client) else "no known cancel method found",
                )
            )
            checks.append(
                PreflightCheck(
                    name="open_orders_method",
                    status="pass" if _has_open_orders_method(client) else "warn",
                    detail=(
                        "supported open orders method found"
                        if _has_open_orders_method(client)
                        else "no known open orders method found"
                    ),
                )
            )
            if cfg.polymarket.rust_hotpath_enabled:
                try:
                    rust_session(cfg).status()
                except Exception as e:
                    checks.append(PreflightCheck(name="rust_hotpath_session", status="fail", detail=str(e)))
                else:
                    checks.append(PreflightCheck(name="rust_hotpath_session", status="pass", detail="rust daemon responded"))
    return checks


def _rust_checks(cfg: AppConfig) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []
    workspace = Path(__file__).resolve().parents[3] / "rust"
    binary = workspace / "target" / "debug" / "stonks-polymarket-hotpath"
    checks.append(
        PreflightCheck(
            name="rust_workspace",
            status="pass" if workspace.exists() else "fail",
            detail=str(workspace),
        )
    )
    using_cargo = cfg.polymarket.rust_hotpath_use_cargo or not binary.exists()
    if using_cargo:
        cargo = shutil.which("cargo")
        checks.append(
            PreflightCheck(
                name="rust_cargo",
                status="pass" if cargo else "fail",
                detail=cargo or "cargo not found",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                name="rust_binary",
                status="pass",
                detail=str(binary),
            )
        )
    return checks


def _dependency_check(name: str, module: str) -> PreflightCheck:
    try:
        __import__(module)
    except Exception as e:
        return PreflightCheck(name=name, status="fail", detail=str(e))
    return PreflightCheck(name=name, status="pass", detail=f"{module} import ok")


def _writable_check(name: str, path: Path) -> PreflightCheck:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except Exception as e:
        return PreflightCheck(name=name, status="fail", detail=str(e))
    return PreflightCheck(name=name, status="pass", detail=str(path))


def _has_cancel_method(client: object) -> bool:
    return any(hasattr(client, name) for name in ("cancel", "cancel_order", "cancel_orders"))


def _has_open_orders_method(client: object) -> bool:
    return any(hasattr(client, name) for name in ("get_open_orders", "get_orders", "open_orders", "list_open_orders"))
