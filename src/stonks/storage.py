from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def default_state_dir() -> Path:
    return Path.home() / ".local" / "share" / "stonks"


@dataclass(frozen=True)
class RunRecord:
    started_at: str
    tickers: list[str]
    report_path: str | None


def state_path() -> Path:
    return default_state_dir() / "state.json"


def load_state() -> dict:
    path = state_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def save_last_run(tickers: list[str], report_path: Path | None) -> None:
    state = load_state()
    state["last_run"] = {
        "started_at": datetime.utcnow().isoformat() + "Z",
        "tickers": tickers,
        "report_path": str(report_path) if report_path else None,
    }
    save_state(state)


def get_last_report_path() -> Path | None:
    state = load_state()
    last = state.get("last_run") if isinstance(state, dict) else None
    if not isinstance(last, dict):
        return None
    p = last.get("report_path")
    if not p:
        return None
    try:
        return Path(p)
    except Exception:
        return None
