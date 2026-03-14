from __future__ import annotations

from datetime import date, datetime, timedelta

from schema import DATE_FORMAT, touch_card


def sm2_review(card: dict, grade: int, config: dict | None = None) -> dict:
    min_ease = 1.3
    easy_bonus = 1.3
    hard_factor = 0.8
    if config and "srs" in config:
        min_ease = config["srs"].get("minimum_ease", min_ease)
        easy_bonus = config["srs"].get("easy_bonus", easy_bonus)
        hard_factor = config["srs"].get("hard_factor", hard_factor)
    ef = float(card.get("ease_factor", 2.5))
    interval = int(card.get("interval", 0))
    reps = int(card.get("repetitions", 0))
    match grade:
        case 0:
            reps = 0
            interval = 1
            ef = max(min_ease, ef - 0.2)
        case 1:
            if reps <= 1:
                interval = 1
            else:
                interval = max(1, round(interval * hard_factor))
            reps += 1
            ef = max(min_ease, ef - 0.15)
        case 2:
            if reps == 0:
                interval = 1
            elif reps == 1:
                interval = 6
            else:
                interval = max(1, round(interval * ef))
            reps += 1
        case 3:
            if reps == 0:
                interval = 1
            elif reps == 1:
                interval = 6
            else:
                interval = max(1, round(interval * ef))
            interval = max(1, round(interval * easy_bonus))
            ef += 0.15
            reps += 1
        case _:
            raise ValueError(f"Unsupported review grade '{grade}'.")
    card["ease_factor"] = ef
    card["interval"] = interval
    card["repetitions"] = reps
    card["card_date"] = (date.today() + timedelta(days=interval)).strftime(DATE_FORMAT)
    touch_card(card)
    return card


def active_cards(cards: list[dict], include_suspended: bool = False) -> list[dict]:
    if include_suspended:
        return list(cards)
    return [card for card in cards if not card.get("suspended", False)]


def cards_due(cards: list[dict], include_suspended: bool = False) -> list[dict]:
    today = date.today()
    result = []
    for card in active_cards(cards, include_suspended):
        try:
            card_date = datetime.strptime(card["card_date"], DATE_FORMAT).date()
            if card_date <= today:
                result.append(card)
        except (TypeError, ValueError, KeyError):
            result.append(card)
    return result


def cards_due_count(cards: list[dict], include_suspended: bool = False) -> int:
    return len(cards_due(cards, include_suspended))


def next_review_date(cards: list[dict]) -> str:
    future_dates = []
    for card in active_cards(cards):
        try:
            future_dates.append(datetime.strptime(card["card_date"], DATE_FORMAT).date())
        except (TypeError, ValueError, KeyError):
            continue
    if not future_dates:
        return "N/A"
    return min(future_dates).strftime(DATE_FORMAT)
