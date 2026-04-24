from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from stonks_cli.logging_utils import log_suppressed_exception
from stonks_cli.polymarket.models import RuntimeStatus
from stonks_cli.paths import default_state_dir


def runtime_state_path() -> Path:
    return default_state_dir() / "polymarket_runtime.json"


def load_runtime_status() -> RuntimeStatus:
    path = runtime_state_path()
    if not path.exists():
        return RuntimeStatus(
            mode="polymarket",
            state="idle",
            paper=True,
            last_scan_at=None,
            last_scan_count=0,
            last_pass_count=0,
            last_error=None,
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log_suppressed_exception(context="polymarket.storage.load_runtime_status", error=e, path=path)
        return RuntimeStatus(
            mode="polymarket",
            state="error",
            paper=True,
            last_scan_at=None,
            last_scan_count=0,
            last_pass_count=0,
            last_error=str(e),
        )
    return RuntimeStatus(
        mode=str(payload.get("mode") or "polymarket"),
        state=str(payload.get("state") or "idle"),
        paper=bool(payload.get("paper", True)),
        last_scan_at=payload.get("last_scan_at"),
        last_scan_count=int(payload.get("last_scan_count") or 0),
        last_pass_count=int(payload.get("last_pass_count") or 0),
        last_error=payload.get("last_error"),
    )


def save_runtime_status(status: RuntimeStatus) -> None:
    path = runtime_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(status), indent=2), encoding="utf-8")
