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


def _load_all_events() -> tuple[list[dict], int]:
    path = history_path()
    if not os.path.exists(path):
        return ([], 0)
    events = []
    invalid_lines = 0
    with open(path, "r", encoding="utf-8") as fhand:
        for line in fhand:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                invalid_lines += 1
                continue
            if not isinstance(event, dict):
                invalid_lines += 1
                continue
            events.append(event)
    return (events, invalid_lines)


def _event_matches(
    event: dict,
    *,
    deck_name: str | None = None,
    set_name: str | None = None,
    card_id: str | None = None,
    since: datetime | None = None,
    before: datetime | None = None,
) -> bool:
    if deck_name and event.get("deck_name") != deck_name:
        return False
    if set_name and event.get("set_name") != set_name:
        return False
    if card_id and event.get("after", {}).get("card_id") != card_id:
        return False
    if since or before:
        try:
            event_time = datetime.fromisoformat(event["timestamp"])
        except (KeyError, TypeError, ValueError):
            return False
        if since and event_time < since:
            return False
        if before and event_time >= before:
            return False
    return True


def load_history(
    *,
    deck_name: str | None = None,
    set_name: str | None = None,
    card_id: str | None = None,
    since: datetime | None = None,
) -> list[dict]:
    events, _ = _load_all_events()
    return [
        event
        for event in events
        if _event_matches(event, deck_name=deck_name, set_name=set_name, card_id=card_id, since=since)
    ]


def rewrite_history(events: list[dict]) -> None:
    with open(history_path(), "w", encoding="utf-8") as fhand:
        for event in events:
            fhand.write(json.dumps(event))
            fhand.write("\n")


def export_history(
    destination: str,
    *,
    deck_name: str | None = None,
    set_name: str | None = None,
    card_id: str | None = None,
    since: datetime | None = None,
    before: datetime | None = None,
    format: str = "jsonl",
) -> dict:
    events = [
        deepcopy(event)
        for event in load_history(deck_name=deck_name, set_name=set_name, card_id=card_id, since=since)
        if _event_matches(event, before=before)
    ]
    parent = os.path.dirname(destination)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(destination, "w", encoding="utf-8") as fhand:
        if format == "json":
            json.dump(events, fhand, indent=2)
        else:
            for event in events:
                fhand.write(json.dumps(event))
                fhand.write("\n")
    return {"exported": len(events), "destination": destination}


def prune_history(
    *,
    deck_name: str | None = None,
    set_name: str | None = None,
    card_id: str | None = None,
    since: datetime | None = None,
    before: datetime | None = None,
) -> dict:
    events, invalid_lines = _load_all_events()
    kept = []
    removed = []
    for event in events:
        if _event_matches(
            event,
            deck_name=deck_name,
            set_name=set_name,
            card_id=card_id,
            since=since,
            before=before,
        ):
            removed.append(event)
        else:
            kept.append(event)
    rewrite_history(kept)
    return {"removed": len(removed), "remaining": len(kept), "invalid_lines": invalid_lines}


def archive_history(
    destination: str,
    *,
    deck_name: str | None = None,
    set_name: str | None = None,
    card_id: str | None = None,
    since: datetime | None = None,
    before: datetime | None = None,
    format: str = "jsonl",
) -> dict:
    events, invalid_lines = _load_all_events()
    kept = []
    archived = []
    for event in events:
        if _event_matches(
            event,
            deck_name=deck_name,
            set_name=set_name,
            card_id=card_id,
            since=since,
            before=before,
        ):
            archived.append(event)
        else:
            kept.append(event)
    parent = os.path.dirname(destination)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(destination, "w", encoding="utf-8") as fhand:
        if format == "json":
            json.dump(archived, fhand, indent=2)
        else:
            for event in archived:
                fhand.write(json.dumps(event))
                fhand.write("\n")
    rewrite_history(kept)
    return {
        "archived": len(archived),
        "remaining": len(kept),
        "invalid_lines": invalid_lines,
        "destination": destination,
    }


def rebuild_history() -> dict:
    events, invalid_lines = _load_all_events()
    rewrite_history(events)
    return {"events": len(events), "dropped_lines": invalid_lines}


def pop_last_review_event(
    *,
    deck_name: str | None = None,
    set_name: str | None = None,
    card_id: str | None = None,
) -> dict | None:
    events, _ = _load_all_events()
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        if _event_matches(event, deck_name=deck_name, set_name=set_name, card_id=card_id):
            removed = deepcopy(event)
            del events[index]
            rewrite_history(events)
            return removed
    return None


def latest_review_for_card(card_id: str, *, deck_name: str | None = None) -> dict | None:
    latest = None
    for event in load_history(deck_name=deck_name, card_id=card_id):
        latest = deepcopy(event)
    return latest
