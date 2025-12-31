from __future__ import annotations

from datetime import datetime
from pathlib import Path

from stonks.llm.backends import ChatMessage


def default_transcript_path() -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return Path("reports") / f"chat_transcript_{ts}.txt"


def write_transcript(messages: list[ChatMessage], out_path: Path) -> Path:
    out_path = out_path.expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for m in messages:
        if m.role == "system":
            continue
        lines.append(f"[{m.role}]\n{m.content}\n")
    out_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return out_path
