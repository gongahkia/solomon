from __future__ import annotations

import time
from copy import deepcopy

from deck_ops import restore_card
from history import log_review_event, pop_last_review_event
from srs import active_cards, cards_due, cards_due_count, next_review_date, sm2_review


def review_mode_from_due_only(due_only: bool) -> str:
    return "due" if due_only else "all"


def review_cards_for_mode(cards: list[dict], review_mode: str) -> list[dict]:
    return cards_due(cards) if review_mode == "due" else active_cards(cards)


def start_session(cards: list[dict], review_mode: str) -> dict:
    return {
        "review_mode": review_mode,
        "review_cards": review_cards_for_mode(cards, review_mode),
        "history": [],
        "counts": {0: 0, 1: 0, 2: 0, 3: 0},
        "start_time": time.time(),
    }


def apply_review(
    session: dict,
    *,
    deck_name: str,
    set_name: str,
    card: dict,
    grade: int,
    config: dict,
    leech_handler=None,
) -> dict:
    before = deepcopy(card)
    sm2_review(card, grade, config)
    if leech_handler is not None:
        leech_handler(card, config)
    log_review_event(deck_name, set_name, before, card, grade, session["review_mode"])
    session["counts"][grade] += 1
    event = {"card": card, "snapshot": before, "grade": grade}
    session["history"].append(event)
    return event


def undo_last_review(session: dict, *, deck_name: str, set_name: str) -> dict | None:
    if not session["history"]:
        return None
    last = session["history"].pop()
    restore_card(last["card"], last["snapshot"])
    pop_last_review_event(deck_name=deck_name, set_name=set_name, card_id=last["card"].get("id"))
    session["counts"][last["grade"]] -= 1
    return last


def reviewed_count(session: dict) -> int:
    return sum(session["counts"].values())


def session_elapsed_minutes(session: dict) -> float:
    return (time.time() - session["start_time"]) / 60


def review_summary_lines(session: dict, cards: list[dict]) -> list[str]:
    counts = session["counts"]
    return [
        f"Reviewed {reviewed_count(session)} cards in {session_elapsed_minutes(session):.1f} minutes.",
        f"Again {counts[0]} | Hard {counts[1]} | Good {counts[2]} | Easy {counts[3]}",
        f"Remaining due today: {cards_due_count(cards)}",
    ]


def next_due_text(cards: list[dict]) -> str:
    return next_review_date(cards)
