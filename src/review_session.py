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
        "votes": {},
        "vote_lookup": {},
        "start_time": time.time(),
    }


def _vote_key(card: dict) -> str:
    return str(card.get("id") or id(card))


def set_vote(session: dict, card: dict, vote: int) -> int:
    key = _vote_key(card)
    session["vote_lookup"][key] = card
    if vote not in {-1, 0, 1}:
        vote = 0
    if vote == 0:
        session["votes"].pop(key, None)
        return 0
    session["votes"][key] = vote
    return vote


def get_vote(session: dict, card: dict) -> int:
    return int(session["votes"].get(_vote_key(card), 0))


def downvoted_cards(session: dict) -> list[dict]:
    cards = []
    for key, vote in session.get("votes", {}).items():
        if vote < 0 and key in session.get("vote_lookup", {}):
            cards.append(session["vote_lookup"][key])
    return cards


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
    downvoted = len(downvoted_cards(session))
    return [
        f"Reviewed {reviewed_count(session)} cards in {session_elapsed_minutes(session):.1f} minutes.",
        f"Again {counts[0]} | Hard {counts[1]} | Good {counts[2]} | Easy {counts[3]}",
        f"Downvoted this session: {downvoted}",
        f"Remaining due today: {cards_due_count(cards)}",
    ]


def next_due_text(cards: list[dict]) -> str:
    return next_review_date(cards)
