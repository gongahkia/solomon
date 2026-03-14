from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime

from analytics import overdue_days
from schema import DATE_FORMAT, is_leech, new_card, touch_card
from tui import COLORS


def parse_tags(raw_tags: str) -> list[str]:
    return [tag.strip() for tag in raw_tags.split(",") if tag.strip()]


def restore_card(card: dict, snapshot: dict) -> None:
    card.clear()
    card.update(deepcopy(snapshot))


def duplicate_card(card: dict, config: dict) -> dict:
    name = card.get("card_name", "")
    if not name.endswith(" (copy)"):
        name = f"{name} (copy)"
    return new_card(
        card_name=name,
        card_info=card.get("card_info", ""),
        card_add_info=card.get("card_add_info", ""),
        tags=card.get("tags", []),
        config=config,
    )


def card_status(card: dict) -> tuple[str, int]:
    if card.get("suspended"):
        return ("Suspended", COLORS["muted"])
    overdue = overdue_days(card)
    if overdue:
        return (f"Overdue {overdue}d", COLORS["error"])
    try:
        card_date = datetime.strptime(card["card_date"], DATE_FORMAT).date()
    except (TypeError, ValueError, KeyError):
        return ("Due (invalid date)", COLORS["error"])
    if card_date <= date.today():
        return ("Due", COLORS["error"])
    return (f"Next {card_date.strftime(DATE_FORMAT)}", COLORS["success"])


def card_detail(card: dict, config: dict) -> tuple[str, int]:
    status, color = card_status(card)
    extras = [card.get("state", "new")]
    if is_leech(card, config):
        extras.append("leech")
    tags = card.get("tags", [])
    if tags:
        extras.append(f"tags:{','.join(tags)}")
    return (f"{status} | {' | '.join(extras)}", color)


def move_card(sets: dict, source_set: str, index: int, target_set: str) -> dict:
    card = sets[source_set].pop(index)
    sets.setdefault(target_set, []).append(card)
    touch_card(card)
    return card


def reorder_card(cards: list[dict], index: int, direction: int) -> int:
    target_index = index + direction
    if target_index < 0 or target_index >= len(cards):
        return index
    cards[target_index], cards[index] = cards[index], cards[target_index]
    touch_card(cards[target_index])
    touch_card(cards[index])
    return target_index


def toggle_suspend(card: dict) -> bool:
    card["suspended"] = not card.get("suspended", False)
    touch_card(card)
    return card["suspended"]
