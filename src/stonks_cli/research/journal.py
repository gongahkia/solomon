from __future__ import annotations

import json
from pathlib import Path

from stonks_cli.logging_utils import log_suppressed_exception
from stonks_cli.paths import default_state_dir
from stonks_cli.research.models import DecisionRecord


def decision_journal_path() -> Path:
    return default_state_dir() / "research_decisions.jsonl"


def append_decision(record: DecisionRecord, path: Path | None = None) -> None:
    use_path = path or decision_journal_path()
    try:
        use_path.parent.mkdir(parents=True, exist_ok=True)
        with use_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
    except Exception as e:
        log_suppressed_exception(context="research.journal.append_decision", error=e, path=use_path)


def read_decisions(limit: int = 100, path: Path | None = None) -> list[dict[str, object]]:
    use_path = path or decision_journal_path()
    if not use_path.exists():
        return []
    try:
        lines = use_path.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        log_suppressed_exception(context="research.journal.read_decisions", error=e, path=use_path)
        return []

    out: list[dict[str, object]] = []
    for line in lines[-max(0, limit) :]:
        try:
            payload = json.loads(line)
        except Exception as e:
            log_suppressed_exception(context="research.journal.parse_line", error=e, line=line)
            continue
        if isinstance(payload, dict):
            out.append(payload)
    return out

