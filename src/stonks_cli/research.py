from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stonks_cli.paths import default_state_dir


@dataclass(frozen=True)
class ResearchEntry:
    entry_id: str
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchEntry":
        return cls(
            entry_id=str(data.get("entry_id") or uuid.uuid4().hex[:12]),
            title=str(data.get("title") or ""),
            body=str(data.get("body") or ""),
            tags=[str(t) for t in (data.get("tags") or [])],
            created_at=str(data.get("created_at") or datetime.now(UTC).isoformat().replace("+00:00", "Z")),
            metadata=dict(data.get("metadata") or {}),
        )


def research_log_path() -> Path:
    path = default_state_dir() / "research.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def add_research_entry(title: str, body: str, *, tags: list[str] | None = None) -> ResearchEntry:
    entry = ResearchEntry(
        entry_id=uuid.uuid4().hex[:12],
        title=(title or "").strip(),
        body=(body or "").strip(),
        tags=[t.strip() for t in (tags or []) if t.strip()],
    )
    if not entry.title:
        raise ValueError("research title must be non-empty")
    if not entry.body:
        raise ValueError("research body must be non-empty")
    with research_log_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
    return entry


def list_research_entries(limit: int = 20) -> list[ResearchEntry]:
    path = research_log_path()
    if not path.exists():
        return []
    rows: list[ResearchEntry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(ResearchEntry.from_dict(json.loads(line)))
        except Exception:
            continue
    return list(reversed(rows[-max(1, limit) :]))


def search_research_entries(query: str, *, limit: int = 20) -> list[ResearchEntry]:
    q = (query or "").strip().lower()
    if not q:
        raise ValueError("search query must be non-empty")
    matches: list[ResearchEntry] = []
    for entry in list_research_entries(limit=10_000):
        haystack = " ".join([entry.title, entry.body, " ".join(entry.tags)]).lower()
        if q in haystack:
            matches.append(entry)
        if len(matches) >= limit:
            break
    return matches
