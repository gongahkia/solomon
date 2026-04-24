from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stonks_cli.logging_utils import log_suppressed_exception
from stonks_cli.paths import default_state_dir


def journal_path() -> Path:
    return default_state_dir() / "polymarket_journal.jsonl"


def append_journal(event: str, **fields: Any) -> None:
    path = journal_path()
    payload = {"event": event, **fields}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception as e:
        log_suppressed_exception(context="polymarket.journal.append", error=e, path=path, journal_event=event)


def read_journal(limit: int = 100) -> list[dict[str, Any]]:
    path = journal_path()
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        log_suppressed_exception(context="polymarket.journal.read", error=e, path=path)
        return []
    for line in lines[-max(0, limit) :]:
        try:
            payload = json.loads(line)
        except Exception as e:
            log_suppressed_exception(context="polymarket.journal.parse_line", error=e, line=line)
            continue
        if isinstance(payload, dict):
            out.append(payload)
    return out
