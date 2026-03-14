from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime

from storage import ensure_config_dir

HISTORY_FILENAME = "history.jsonl"


def history_path() -> str:
    return os.path.join(ensure_config_dir(), HISTORY_FILENAME)


def _history_snapshot(card: dict) -> dict:
    return {
        "card_id": card.get("id"),
        "card_name": card.get("card_name", ""),
        "card_date": card.get("card_date", ""),
        "ease_factor": card.get("ease_factor", 0.0),
        "interval": card.get("interval", 0),
        "repetitions": card.get("repetitions", 0),
        "state": card.get("state", "new"),
        "step_index": card.get("step_index", 0),
        "lapses": card.get("lapses", 0),
        "suspended": card.get("suspended", False),
    }


def log_review_event(
    deck_name: str,
    set_name: str,
    card_before: dict,
    card_after: dict,
    grade: int,
    session_mode: str,
) -> None:
    event = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "deck_name": deck_name,
        "set_name": set_name,
        "grade": int(grade),
        "session_mode": session_mode,
        "before": _history_snapshot(card_before),
        "after": _history_snapshot(card_after),
    }
    with open(history_path(), "a", encoding="utf-8") as fhand:
        fhand.write(json.dumps(event))
        fhand.write("\n")


def load_history(
    *,
    deck_name: str | None = None,
    set_name: str | None = None,
    card_id: str | None = None,
    since: datetime | None = None,
) -> list[dict]:
    path = history_path()
    if not os.path.exists(path):
        return []
    events = []
    with open(path, "r", encoding="utf-8") as fhand:
        for line in fhand:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if deck_name and event.get("deck_name") != deck_name:
                continue
            if set_name and event.get("set_name") != set_name:
                continue
            if card_id and event.get("after", {}).get("card_id") != card_id:
                continue
            if since:
                try:
                    event_time = datetime.fromisoformat(event["timestamp"])
                except (KeyError, TypeError, ValueError):
                    continue
                if event_time < since:
                    continue
            events.append(event)
    return events


def latest_review_for_card(card_id: str, *, deck_name: str | None = None) -> dict | None:
    latest = None
    for event in load_history(deck_name=deck_name, card_id=card_id):
        latest = deepcopy(event)
    return latest
