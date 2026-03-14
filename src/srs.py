from __future__ import annotations

from datetime import date, datetime, timedelta

from schema import DATE_FORMAT, record_grade, touch_card


def _interval_cap(interval: int, max_interval: int) -> int:
    return max(1, min(max_interval, interval))


def _review_config(config: dict | None) -> dict:
    srs = (config or {}).get("srs", {})
    return {
        "minimum_ease": srs.get("minimum_ease", 1.3),
        "easy_bonus": srs.get("easy_bonus", 1.3),
        "hard_factor": srs.get("hard_factor", 0.8),
        "learning_steps": srs.get("learning_steps", [1, 3]),
        "relearning_steps": srs.get("relearning_steps", [1, 3]),
        "graduating_interval": srs.get("graduating_interval", 6),
        "easy_interval": srs.get("easy_interval", 8),
        "max_interval": srs.get("max_interval", 365),
    }


def _learning_review(card: dict, grade: int, steps: list[int], cfg: dict) -> tuple[int, int, str, int, float]:
    ef = float(card.get("ease_factor", 2.5))
    min_ease = cfg["minimum_ease"]
    step_index = int(card.get("step_index", 0))
    reps = int(card.get("repetitions", 0))
    stage = card.get("state", "new")
    if grade == 0:
        step_index = 0
        interval = steps[step_index]
        reps = 0
        ef = max(min_ease, ef - 0.2)
    elif grade == 1:
        interval = steps[min(step_index, len(steps) - 1)]
        reps = 0
        ef = max(min_ease, ef - 0.15)
    elif grade == 2:
        if step_index < len(steps) - 1:
            step_index += 1
            interval = steps[step_index]
            reps = 0
        else:
            stage = "review"
            step_index = 0
            interval = cfg["graduating_interval"]
            reps = max(1, reps + 1)
    elif grade == 3:
        stage = "review"
        step_index = 0
        interval = cfg["easy_interval"]
        reps = max(1, reps + 1)
        ef += 0.15
    else:
        raise ValueError(f"Unsupported review grade '{grade}'.")
    return interval, reps, stage, step_index, ef


def sm2_review(card: dict, grade: int, config: dict | None = None) -> dict:
    cfg = _review_config(config)
    ef = float(card.get("ease_factor", 2.5))
    interval = int(card.get("interval", 0))
    reps = int(card.get("repetitions", 0))
    stage = card.get("state", "review" if reps > 0 or interval > 0 else "new")
    step_index = int(card.get("step_index", 0))
    min_ease = cfg["minimum_ease"]
    learning_steps = cfg["learning_steps"]
    relearning_steps = cfg["relearning_steps"]
    max_interval = cfg["max_interval"]
    record_grade(card, grade)
    if stage == "new":
        interval, reps, stage, step_index, ef = _learning_review(card, grade, learning_steps, cfg)
    elif stage == "relearning":
        interval, reps, stage, step_index, ef = _learning_review(card, grade, relearning_steps, cfg)
    else:
        match grade:
            case 0:
                stage = "relearning"
                step_index = 0
                reps = 0
                interval = relearning_steps[0]
                ef = max(min_ease, ef - 0.2)
                card["lapses"] = int(card.get("lapses", 0)) + 1
            case 1:
                if reps <= 1:
                    interval = learning_steps[0]
                else:
                    interval = max(1, round(interval * cfg["hard_factor"]))
                reps += 1
                ef = max(min_ease, ef - 0.15)
            case 2:
                if reps == 0:
                    interval = learning_steps[0]
                elif reps == 1:
                    interval = cfg["graduating_interval"]
                else:
                    interval = max(1, round(interval * ef))
                reps += 1
            case 3:
                if reps == 0:
                    interval = cfg["easy_interval"]
                elif reps == 1:
                    interval = cfg["easy_interval"]
                else:
                    interval = max(1, round(interval * ef))
                    interval = max(interval, cfg["easy_interval"])
                    interval = round(interval * cfg["easy_bonus"])
                ef += 0.15
                reps += 1
            case _:
                raise ValueError(f"Unsupported review grade '{grade}'.")
    interval = _interval_cap(interval, max_interval)
    card["ease_factor"] = ef
    card["interval"] = interval
    card["repetitions"] = reps
    card["state"] = stage
    card["step_index"] = step_index
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
