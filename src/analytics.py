from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from schema import DATE_FORMAT, is_leech
from srs import active_cards, cards_due, cards_due_count


def overdue_days(card: dict) -> int:
    try:
        due_date = datetime.strptime(card["card_date"], DATE_FORMAT).date()
    except (KeyError, TypeError, ValueError):
        return 0
    return max(0, (date.today() - due_date).days)


def created_within_days(card: dict, days: int) -> bool:
    try:
        created = datetime.fromisoformat(card["created_at"]).date()
    except (KeyError, TypeError, ValueError):
        return False
    return created >= (date.today() - timedelta(days=days))


def grade_counts_from_cards(cards: list[dict]) -> dict:
    counts = {"again": 0, "hard": 0, "good": 0, "easy": 0}
    for card in cards:
        counts["again"] += int(card.get("again_count", 0))
        counts["hard"] += int(card.get("hard_count", 0))
        counts["good"] += int(card.get("good_count", 0))
        counts["easy"] += int(card.get("easy_count", 0))
    return counts


def grade_counts_from_history(events: list[dict]) -> dict:
    counts = {"again": 0, "hard": 0, "good": 0, "easy": 0}
    key_map = {0: "again", 1: "hard", 2: "good", 3: "easy"}
    for event in events:
        grade = event.get("grade")
        if grade in key_map:
            counts[key_map[grade]] += 1
    return counts


def review_activity(events: list[dict], days: int = 14) -> list[tuple[date, int]]:
    today = date.today()
    counts = defaultdict(int)
    for event in events:
        try:
            event_day = datetime.fromisoformat(event["timestamp"]).date()
        except (KeyError, TypeError, ValueError):
            continue
        counts[event_day] += 1
    activity = []
    for offset in range(days - 1, -1, -1):
        target = today - timedelta(days=offset)
        activity.append((target, counts[target]))
    return activity


def forecast_counts(cards: list[dict], days: int = 7) -> list[tuple[date, int]]:
    today = date.today()
    day_counts = []
    for offset in range(days):
        target = today + timedelta(days=offset)
        count = 0
        for card in active_cards(cards):
            try:
                card_date = datetime.strptime(card["card_date"], DATE_FORMAT).date()
                if card_date == target:
                    count += 1
            except (TypeError, ValueError, KeyError):
                if offset == 0:
                    count += 1
        day_counts.append((target, count))
    return day_counts


def due_today(cards: list[dict]) -> int:
    today = date.today()
    count = 0
    for card in active_cards(cards):
        try:
            card_date = datetime.strptime(card["card_date"], DATE_FORMAT).date()
            if card_date == today:
                count += 1
        except (TypeError, ValueError, KeyError):
            count += 1
    return count


def retention_percent(events: list[dict]) -> float:
    grades = grade_counts_from_history(events)
    total_reviews = sum(grades.values())
    if not total_reviews:
        return 0.0
    correct = grades["hard"] + grades["good"] + grades["easy"]
    return correct / total_reviews * 100


def stats_pages(valid_statuses: list[dict], history_events: list[dict], config: dict) -> list[tuple[str, list[str]]]:
    all_cards = []
    set_rows = []
    for status in valid_statuses:
        for set_name, cards in status["sets"].items():
            all_cards.extend(cards)
            set_rows.append(
                {
                    "label": f"{status['filename']}::{set_name}",
                    "total": len(cards),
                    "due": cards_due_count(cards),
                    "overdue": len([card for card in cards if overdue_days(card) > 0]),
                    "leech": len([card for card in cards if is_leech(card, config)]),
                    "recent": len([card for card in cards if created_within_days(card, 7)]),
                }
            )
    active = active_cards(all_cards)
    suspended = len([card for card in all_cards if card.get("suspended")])
    leech = len([card for card in all_cards if is_leech(card, config)])
    recent_cards = len([card for card in all_cards if created_within_days(card, 7)])
    due = len(cards_due(all_cards))
    overdue_bucket = {
        "today": due_today(all_cards),
        "1-7d": len([card for card in active if 1 <= overdue_days(card) <= 7]),
        "8-30d": len([card for card in active if 8 <= overdue_days(card) <= 30]),
        "30+d": len([card for card in active if overdue_days(card) > 30]),
    }
    card_grades = grade_counts_from_cards(all_cards)
    history_grades = grade_counts_from_history(history_events)
    avg_ease = sum(card.get("ease_factor", 2.5) for card in all_cards) / len(all_cards) if all_cards else 0.0
    forecast = forecast_counts(all_cards, 7)
    activity = review_activity(history_events, 14)
    overview = [
        f"Deck files: {len(valid_statuses)}",
        f"Sets: {len(set_rows)}",
        f"Cards: {len(all_cards)} total | {len(active)} active | {suspended} suspended",
        f"Due now: {due} | Leech candidates: {leech} | Added in 7d: {recent_cards}",
        f"Average ease: {avg_ease:.2f}",
        f"Retention from history: {retention_percent(history_events):.1f}% | Reviews logged: {len(history_events)}",
        "",
        f"Current card grades -> Again {card_grades['again']} | Hard {card_grades['hard']} | Good {card_grades['good']} | Easy {card_grades['easy']}",
        f"History grades -> Again {history_grades['again']} | Hard {history_grades['hard']} | Good {history_grades['good']} | Easy {history_grades['easy']}",
        "Overdue buckets",
        f"Due today: {overdue_bucket['today']}",
        f"1-7 days overdue: {overdue_bucket['1-7d']}",
        f"8-30 days overdue: {overdue_bucket['8-30d']}",
        f"30+ days overdue: {overdue_bucket['30+d']}",
    ]
    forecast_lines = []
    max_forecast = max((count for _, count in forecast), default=1) or 1
    for target, count in forecast:
        blocks = "█" * round(count / max_forecast * 20) if count else ""
        forecast_lines.append(f"{target.strftime('%a %d/%m')}: {blocks} {count}")
    activity_lines = []
    max_activity = max((count for _, count in activity), default=1) or 1
    for target, count in activity:
        blocks = "█" * round(count / max_activity * 20) if count else ""
        activity_lines.append(f"{target.strftime('%a %d/%m')}: {blocks} {count}")
    workload_lines = []
    for row in sorted(set_rows, key=lambda item: (-item["due"], -item["overdue"], item["label"]))[:12]:
        workload_lines.append(
            f"{row['label']}: {row['due']} due | {row['overdue']} overdue | {row['leech']} leech | {row['recent']} new7d"
        )
    if not workload_lines:
        workload_lines = ["No set data available."]
    return [
        ("Overview", overview),
        ("Forecast", forecast_lines),
        ("Review Activity", activity_lines or ["No history yet."]),
        ("Workload", workload_lines),
    ]
