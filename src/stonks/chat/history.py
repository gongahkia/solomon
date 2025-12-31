from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from stonks.llm.backends import ChatMessage
from stonks.storage import default_state_dir


@dataclass(frozen=True)
class ChatRecord:
    ts: str
    role: str
    content: str


def chat_history_path() -> Path:
    return default_state_dir() / "chat_history.jsonl"


def append_chat_message(role: str, content: str) -> None:
    rec = ChatRecord(ts=datetime.utcnow().isoformat() + "Z", role=role, content=content)
    path = chat_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec.__dict__) + "\n")


def load_chat_history(limit: int = 50) -> list[ChatMessage]:
    path = chat_history_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[ChatMessage] = []
    for line in lines[-limit:]:
        try:
            obj = json.loads(line)
            role = str(obj.get("role") or "")
            content = str(obj.get("content") or "")
            if not role or not content:
                continue
            out.append(ChatMessage(role=role, content=content))
        except Exception:
            continue
    return out
