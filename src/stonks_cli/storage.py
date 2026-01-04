from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def default_state_dir() -> Path:
    from stonks_cli.paths import default_state_dir as _default_state_dir

    return _default_state_dir()


@dataclass(frozen=True)
class RunRecord:
    started_at: str
    tickers: list[str]
    report_path: str | None
    json_path: str | None = None


def state_path() -> Path:
    return default_state_dir() / "state.json"


def history_path() -> Path:
    return default_state_dir() / "history.jsonl"


def load_state() -> dict:
    path = state_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def save_last_run(tickers: list[str], report_path: Path | None, json_path: Path | None = None) -> None:
    state = load_state()
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    record = {
        "started_at": started_at,
        "tickers": tickers,
        "report_path": str(report_path) if report_path else None,
        "json_path": str(json_path) if json_path else None,
    }
    state["last_run"] = {
        **record,
    }
    save_state(state)

    hp = history_path()
    hp.parent.mkdir(parents=True, exist_ok=True)
    with hp.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def list_history(limit: int = 20) -> list[RunRecord]:
    hp = history_path()
    if not hp.exists():
        return []
    lines = hp.read_text(encoding="utf-8").splitlines()
    records: list[RunRecord] = []
    # Newest-first ordering.
    for line in reversed(lines[-limit:]):
        try:
            obj = json.loads(line)
            records.append(
                RunRecord(
                    started_at=str(obj.get("started_at")),
                    tickers=list(obj.get("tickers") or []),
                    report_path=obj.get("report_path"),
                    json_path=obj.get("json_path"),
                )
            )
        except Exception:
            continue
    return records


def get_history_record(index: int, *, limit: int = 2000) -> RunRecord:
    if index < 0:
        raise IndexError("index must be >= 0")
    records = list_history(limit=limit)
    if index >= len(records):
        raise IndexError("index out of range")
    return records[index]


def get_last_report_path() -> Path | None:
    last = get_last_run()
    if last is None or not last.report_path:
        return None
    try:
        return Path(last.report_path)
    except Exception:
        return None


def get_last_run() -> RunRecord | None:
    state = load_state()
    last = state.get("last_run") if isinstance(state, dict) else None
    if not isinstance(last, dict):
        return None
    return RunRecord(
        started_at=str(last.get("started_at")),
        tickers=list(last.get("tickers") or []),
        report_path=last.get("report_path"),
        json_path=last.get("json_path"),
    )
