# mypy: ignore-errors

from __future__ import annotations

import csv
import curses
import json
import os
import sys
import time
from copy import deepcopy
from datetime import date, datetime, timedelta

from cli import run_cli
from config import load_config, reset_config, save_config
from import_export import (
    count_duplicates,
    export_to_csv,
    export_to_json,
    export_to_txt,
    import_from_csv,
    import_from_json,
    import_from_txt,
    infer_csv_mapping,
    merge_sets,
    preview_import,
)
from schema import DATE_FORMAT, is_leech, new_card, reset_card_progress, touch_card
from srs import active_cards, cards_due, cards_due_count, next_review_date, sm2_review
from storage import ensure_config_dir, list_sko_files, read_sko, sko_path, write_sko
from tui import COLORS, multiline_input, run_app, select_from_list, text_input


def add_line(stdscr, y: int, x: int, text: str, attr: int = 0) -> None:
    max_x = stdscr.getmaxyx()[1]
    if y < 0 or x >= max_x:
        return
    try:
        stdscr.addstr(y, x, text[: max_x - x - 1], attr)
    except curses.error:
        pass


def wait_for_keys(stdscr, accepted: tuple[int, ...]) -> int:
    while True:
        key = stdscr.getch()
        if key in accepted:
            return key


def show_message(stdscr, title: str, lines: list[str], color_key: str = "info") -> None:
    stdscr.erase()
    add_line(stdscr, 0, 0, title, curses.color_pair(COLORS[color_key]))
    for index, line in enumerate(lines, start=2):
        add_line(stdscr, index, 0, line)
    add_line(stdscr, stdscr.getmaxyx()[0] - 1, 0, "[q] Back", curses.color_pair(COLORS["muted"]))
    stdscr.refresh()
    wait_for_keys(stdscr, (ord("q"), ord("Q"), 27, 10, 13))


def confirm_prompt(stdscr, prompt: str, color_key: str = "error") -> bool:
    stdscr.erase()
    add_line(stdscr, 0, 0, prompt, curses.color_pair(COLORS[color_key]))
    add_line(stdscr, 2, 0, "[y] Yes  [n] No", curses.color_pair(COLORS["muted"]))
    stdscr.refresh()
    return wait_for_keys(stdscr, (ord("y"), ord("Y"), ord("n"), ord("N"), 27)) in (ord("y"), ord("Y"))


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


def created_within_days(card: dict, days: int) -> bool:
    try:
        created = datetime.fromisoformat(card["created_at"]).date()
    except (KeyError, TypeError, ValueError):
        return False
    return created >= (date.today() - timedelta(days=days))


def overdue_days(card: dict) -> int:
    try:
        due_date = datetime.strptime(card["card_date"], DATE_FORMAT).date()
    except (KeyError, TypeError, ValueError):
        return 0
    delta = (date.today() - due_date).days
    return max(0, delta)


def grade_counts(cards: list[dict]) -> dict:
    counts = {"again": 0, "hard": 0, "good": 0, "easy": 0}
    for card in cards:
        counts["again"] += int(card.get("again_count", 0))
        counts["hard"] += int(card.get("hard_count", 0))
        counts["good"] += int(card.get("good_count", 0))
        counts["easy"] += int(card.get("easy_count", 0))
    return counts


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


def create_sko_file(name: str, config: dict) -> str:
    if not name.endswith(".sko"):
        name += ".sko"
    write_sko(name, {}, config)
    return name


def select_sko_file(stdscr, config: dict) -> str | None:
    ensure_config_dir()
    while True:
        statuses = list_sko_files(config)
        valid_statuses = [status for status in statuses if status["valid"]]
        total_cards = sum(sum(len(cards) for cards in status["sets"].values()) for status in valid_statuses)
        total_due = sum(
            sum(cards_due_count(cards) for cards in status["sets"].values()) for status in valid_statuses
        )
        items = []
        for status in statuses:
            if status["valid"]:
                n_sets = len(status["sets"])
                n_cards = sum(len(cards) for cards in status["sets"].values())
                n_due = sum(cards_due_count(cards) for cards in status["sets"].values())
                color = COLORS["error"] if n_due > 0 else COLORS["success"]
                items.append((f"{status['filename']} | {n_sets} sets | {n_cards} cards", f"{n_due} due", color))
            else:
                items.append((f"{status['filename']} | invalid deck", status["error"], COLORS["error"]))
        header = f"Senko | {len(valid_statuses)} valid files | {total_cards} cards | {total_due} due today"
        footer = "[Enter] Open  [n] New file  [d] Delete  [/] Filter  [q] Back"
        if not items:
            items = [("No files found.", "Create one with [n]", COLORS["muted"])]
        choice = select_from_list(
            stdscr,
            header,
            items,
            footer=footer,
            extra_bindings=[("n", "New file"), ("d", "Delete file")],
            searchable=True,
        )
        if choice is None:
            return None
        if isinstance(choice, tuple):
            idx, key = choice
            if key == "n":
                name = text_input(stdscr, "Filename: ", y=0, x=0)
                if name:
                    create_sko_file(name, config)
                continue
            if key == "d" and idx is not None and idx < len(statuses):
                filename = statuses[idx]["filename"]
                should_delete = True
                if config.get("tui", {}).get("confirm_delete", True):
                    should_delete = confirm_prompt(stdscr, f"Delete {filename}?")
                if should_delete:
                    os.remove(sko_path(filename))
                continue
            continue
        if not statuses:
            continue
        selected = statuses[choice]
        if not selected["valid"]:
            show_message(stdscr, selected["filename"], [selected["error"]], "error")
            continue
        return selected["filename"]


def select_flashcard_set(stdscr, sets: dict, filename: str, config: dict) -> tuple[str, list] | None:
    while True:
        set_names = list(sets.keys())
        items = []
        for set_name in set_names:
            cards = sets[set_name]
            detail_text = "Empty"
            color = COLORS["muted"]
            if cards:
                n_due = cards_due_count(cards)
                n_suspended = len([card for card in cards if card.get("suspended")])
                n_leech = len([card for card in cards if is_leech(card, config)])
                detail_text = f"{n_due} due | {n_suspended} suspended | {n_leech} leech"
                color = COLORS["error"] if n_due > 0 else COLORS["success"]
            items.append((f"{set_name} | {len(cards)} cards", detail_text, color))
        if not items:
            items = [("No sets found.", "Create one with [n]", COLORS["muted"])]
        choice = select_from_list(
            stdscr,
            "Select flashcard set",
            items,
            footer="[Enter] Open  [n] New set  [r] Rename  [d] Delete  [/] Filter  [q] Back",
            extra_bindings=[("n", "New set"), ("r", "Rename set"), ("d", "Delete set")],
            searchable=True,
        )
        if choice is None:
            return None
        if isinstance(choice, tuple):
            idx, key = choice
            if key == "n":
                name = text_input(stdscr, "Set name: ", y=0, x=0)
                if name and name not in sets:
                    sets[name] = []
                    write_sko(filename, sets, config)
                continue
            if key == "r" and idx is not None and idx < len(set_names):
                old_name = set_names[idx]
                new_name = text_input(stdscr, "New name: ", initial=old_name, y=0, x=0)
                if new_name and new_name != old_name and new_name not in sets:
                    sets[new_name] = sets.pop(old_name)
                    write_sko(filename, sets, config)
                continue
            if key == "d" and idx is not None and idx < len(set_names):
                set_name = set_names[idx]
                should_delete = True
                if config.get("tui", {}).get("confirm_delete", True):
                    should_delete = confirm_prompt(stdscr, f"Delete '{set_name}'?")
                if should_delete:
                    del sets[set_name]
                    write_sko(filename, sets, config)
                continue
            continue
        if not set_names:
            continue
        selected = set_names[choice]
        return (selected, sets[selected])


def review_mode_screen(stdscr, set_name: str, cards: list[dict]) -> str | None:
    reviewable = active_cards(cards)
    due = cards_due(cards)
    if not reviewable:
        show_message(stdscr, set_name, ["All cards in this set are suspended."], "muted")
        return None
    if not due:
        next_date = next_review_date(cards)
        choice = select_from_list(
            stdscr,
            set_name,
            [
                ("Study all active cards", f"{len(reviewable)} active", COLORS["accent"]),
                ("Back", f"Next due date: {next_date}", COLORS["muted"]),
            ],
            footer="[Enter] Select  [q] Back",
        )
        if choice == 0:
            return "all"
        return None
    choice = select_from_list(
        stdscr,
        set_name,
        [
            ("Review due cards", f"{len(due)} due", COLORS["error"]),
            ("Study all active cards", f"{len(reviewable)} active", COLORS["accent"]),
            ("Back", "", COLORS["muted"]),
        ],
        footer="[Enter] Select  [q] Back",
    )
    if choice == 0:
        return "due"
    if choice == 1:
        return "all"
    return None


def draw_card_front(stdscr, set_name: str, card: dict, index: int, total_cards: int, can_undo: bool, config: dict) -> int:
    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()
        detail, color = card_detail(card, config)
        add_line(stdscr, 0, 0, set_name, curses.color_pair(COLORS["accent"]))
        add_line(stdscr, 0, max(0, max_x - 12), f"{index + 1}/{total_cards}")
        add_line(stdscr, 1, 0, detail, curses.color_pair(color))
        center_y = max_y // 2
        name = card.get("card_name", "")
        add_line(stdscr, center_y, max(0, (max_x - len(name)) // 2), name, curses.A_BOLD)
        footer = "[Space] Show answer  [q] Quit session"
        if can_undo:
            footer += "  [u] Undo last"
        add_line(stdscr, max_y - 1, 0, footer, curses.color_pair(COLORS["muted"]))
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord(" "), 10, 13, ord("q"), ord("Q"), ord("u"), ord("U")):
            return key


def draw_card_back(stdscr, set_name: str, card: dict, index: int, total_cards: int, config: dict) -> int:
    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()
        add_line(stdscr, 0, 0, card.get("card_name", ""), curses.A_BOLD)
        add_line(stdscr, 0, max(0, max_x - 12), f"{index + 1}/{total_cards}")
        status, color = card_status(card)
        extra = f"{set_name} | {status} | {card.get('state', 'new')}"
        if is_leech(card, config):
            extra += " | leech"
        add_line(stdscr, 1, 0, extra, curses.color_pair(color))
        row = 3
        for line in card.get("card_info", "").splitlines() or [""]:
            add_line(stdscr, row, 0, line)
            row += 1
        add_info = card.get("card_add_info", "")
        if add_info:
            row += 1
            for line in add_info.splitlines():
                add_line(stdscr, row, 0, line, curses.color_pair(COLORS["muted"]))
                row += 1
        tags = card.get("tags", [])
        if tags:
            add_line(stdscr, max_y - 3, 0, f"Tags: {', '.join(tags)}", curses.color_pair(COLORS["muted"]))
        add_line(
            stdscr,
            max_y - 1,
            0,
            "[1] Again  [2] Hard  [3] Good  [4] Easy  [q] Quit session",
            curses.color_pair(COLORS["prompt"]),
        )
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord("1"), ord("2"), ord("3"), ord("4"), ord("q"), ord("Q")):
            return key


def maybe_handle_leech(stdscr, card: dict, config: dict) -> None:
    threshold = int(config.get("srs", {}).get("leech_threshold", 8))
    if int(card.get("lapses", 0)) != threshold or card.get("suspended"):
        return
    stdscr.erase()
    add_line(
        stdscr,
        0,
        0,
        f"{card.get('card_name', 'Card')} reached the leech threshold ({threshold} lapses).",
        curses.color_pair(COLORS["prompt"]),
    )
    add_line(stdscr, 2, 0, "[s] Suspend card  [k] Keep active", curses.color_pair(COLORS["muted"]))
    stdscr.refresh()
    key = wait_for_keys(stdscr, (ord("s"), ord("S"), ord("k"), ord("K"), 27))
    if key in (ord("s"), ord("S")):
        card["suspended"] = True
        touch_card(card)


def render_sko_loop(stdscr, set_name: str, cards: list[dict], config: dict) -> tuple[str, list]:
    if not cards:
        show_message(stdscr, set_name, ["This set is empty. Add cards before reviewing."], "muted")
        return (set_name, cards)
    review_mode = review_mode_screen(stdscr, set_name, cards)
    if review_mode is None:
        return (set_name, cards)
    review_cards = cards_due(cards) if review_mode == "due" else active_cards(cards)
    if not review_cards:
        show_message(
            stdscr,
            set_name,
            [f"All caught up. Next review: {next_review_date(cards)}"],
            "success",
        )
        return (set_name, cards)
    start_time = time.time()
    history = []
    session_counts = {0: 0, 1: 0, 2: 0, 3: 0}
    index = 0
    while index < len(review_cards):
        card = review_cards[index]
        front_key = draw_card_front(stdscr, set_name, card, index, len(review_cards), bool(history), config)
        if front_key in (ord("q"), ord("Q")):
            break
        if front_key in (ord("u"), ord("U")) and history:
            last = history.pop()
            restore_card(last["card"], last["snapshot"])
            session_counts[last["grade"]] -= 1
            index = max(0, index - 1)
            continue
        snapshot = deepcopy(card)
        back_key = draw_card_back(stdscr, set_name, card, index, len(review_cards), config)
        if back_key in (ord("q"), ord("Q")):
            break
        grade = int(chr(back_key)) - 1
        sm2_review(card, grade, config)
        maybe_handle_leech(stdscr, card, config)
        session_counts[grade] += 1
        history.append({"card": card, "snapshot": snapshot, "grade": grade})
        index += 1
    elapsed = time.time() - start_time
    reviewed = len(history)
    show_message(
        stdscr,
        set_name,
        [
            f"Reviewed {reviewed} cards in {elapsed / 60:.1f} minutes.",
            f"Again {session_counts[0]} | Hard {session_counts[1]} | Good {session_counts[2]} | Easy {session_counts[3]}",
            f"Remaining due today: {cards_due_count(cards)}",
        ],
        "success",
    )
    return (set_name, cards)


def edit_card_fields(stdscr, title: str, initial: dict | None, config: dict) -> dict | None:
    initial = initial or {}
    name = text_input(stdscr, "Name: ", initial=initial.get("card_name", ""), y=0, x=0)
    if name is None or not name.strip():
        return None
    info = multiline_input(stdscr, f"{title} - Info", initial=initial.get("card_info", ""))
    if info is None:
        return None
    add_info = multiline_input(stdscr, f"{title} - Additional info", initial=initial.get("card_add_info", ""))
    if add_info is None:
        return None
    tags = text_input(stdscr, "Tags (comma-separated): ", initial=",".join(initial.get("tags", [])), y=0, x=0)
    if tags is None:
        return None
    return {
        "card_name": name,
        "card_info": info,
        "card_add_info": add_info,
        "tags": parse_tags(tags),
    }


def edit_sko_card(stdscr, card: dict, config: dict) -> dict | None:
    result = edit_card_fields(stdscr, "Edit card", card, config)
    if result is None:
        return None
    card["card_name"] = result["card_name"]
    card["card_info"] = result["card_info"]
    card["card_add_info"] = result["card_add_info"]
    card["tags"] = result["tags"]
    touch_card(card)
    return card


def add_sko_card(stdscr, config: dict) -> dict | None:
    result = edit_card_fields(stdscr, "Add new card", None, config)
    if result is None:
        return None
    return new_card(
        card_name=result["card_name"],
        card_info=result["card_info"],
        card_add_info=result["card_add_info"],
        tags=result["tags"],
        config=config,
    )


def choose_target_set(stdscr, sets: dict, current_set: str) -> str | None:
    while True:
        set_names = [name for name in sets if name != current_set]
        items = [(name, f"{len(sets[name])} cards", COLORS["info"]) for name in set_names]
        if not items:
            items = [("No other sets found.", "Create one with [n]", COLORS["muted"])]
        choice = select_from_list(
            stdscr,
            f"Move card from {current_set}",
            items,
            footer="[Enter] Select  [n] New set  [q] Cancel",
            extra_bindings=[("n", "New set")],
            searchable=True,
        )
        if choice is None:
            return None
        if isinstance(choice, tuple):
            if choice[1] == "n":
                name = text_input(stdscr, "New set: ", y=0, x=0)
                if name and name not in sets:
                    sets[name] = []
                    return name
            continue
        return set_names[choice]


def manage_cards_loop(stdscr, sets: dict, set_name: str, config: dict) -> tuple[str, dict]:
    while True:
        cards = sets[set_name]
        if not cards:
            choice = select_from_list(
                stdscr,
                set_name,
                [("No cards yet.", "Press [a] to add one", COLORS["muted"])],
                footer="[a] Add card  [q] Back",
                extra_bindings=[("a", "Add card")],
            )
            if isinstance(choice, tuple) and choice[1] == "a":
                new_entry = add_sko_card(stdscr, config)
                if new_entry is not None:
                    cards.append(new_entry)
                continue
            return (set_name, sets)
        items = [(card.get("card_name", "?"), *card_detail(card, config)) for card in cards]
        choice = select_from_list(
            stdscr,
            f"Manage cards in {set_name}",
            items,
            footer="[Enter] Open  [a] Add card  [/] Filter  [q] Back",
            extra_bindings=[("a", "Add card")],
            searchable=True,
        )
        if choice is None:
            return (set_name, sets)
        if isinstance(choice, tuple):
            if choice[1] == "a":
                new_entry = add_sko_card(stdscr, config)
                if new_entry is not None:
                    cards.append(new_entry)
            continue
        card = cards[choice]
        suspend_label = "Unsuspend" if card.get("suspended") else "Suspend"
        action = select_from_list(
            stdscr,
            card.get("card_name", "Card"),
            [
                ("Edit", card.get("card_info", "")[:40], COLORS["info"]),
                ("Duplicate", "Create a fresh copy with reset progress", COLORS["success"]),
                ("Move to set", set_name, COLORS["accent"]),
                ("Move up", "", COLORS["muted"]),
                ("Move down", "", COLORS["muted"]),
                (suspend_label, "", COLORS["muted"]),
                ("Reset progress", f"Stage: {card.get('state', 'new')}", COLORS["prompt"]),
                ("Delete", "", COLORS["error"]),
                ("Back", "", COLORS["muted"]),
            ],
            footer="[Enter] Select  [q] Back",
        )
        if action is None or action == 8:
            continue
        if action == 0:
            updated = edit_sko_card(stdscr, card, config)
            if updated is not None:
                cards[choice] = updated
        elif action == 1:
            cards.insert(choice + 1, duplicate_card(card, config))
        elif action == 2:
            target = choose_target_set(stdscr, sets, set_name)
            if target and target != set_name:
                sets[target].append(cards.pop(choice))
                if not cards:
                    show_message(stdscr, set_name, ["Set is now empty after moving the card."], "muted")
        elif action == 3:
            if choice > 0:
                cards[choice - 1], cards[choice] = cards[choice], cards[choice - 1]
            else:
                show_message(stdscr, set_name, ["Card is already at the top."], "muted")
        elif action == 4:
            if choice < len(cards) - 1:
                cards[choice + 1], cards[choice] = cards[choice], cards[choice + 1]
            else:
                show_message(stdscr, set_name, ["Card is already at the bottom."], "muted")
        elif action == 5:
            card["suspended"] = not card.get("suspended", False)
            touch_card(card)
        elif action == 6:
            reset_card_progress(card, config)
        elif action == 7:
            should_delete = True
            if config.get("tui", {}).get("confirm_delete", True):
                should_delete = confirm_prompt(stdscr, f"Delete '{card.get('card_name', '?')}'?")
            if should_delete:
                del cards[choice]


def config_editor(stdscr, config: dict) -> dict:
    field_specs = [
        ("srs", "initial_ease", "float"),
        ("srs", "minimum_ease", "float"),
        ("srs", "easy_bonus", "float"),
        ("srs", "hard_factor", "float"),
        ("srs", "learning_steps", "list"),
        ("srs", "relearning_steps", "list"),
        ("srs", "graduating_interval", "int"),
        ("srs", "easy_interval", "int"),
        ("srs", "max_interval", "int"),
        ("srs", "leech_threshold", "int"),
        ("tui", "show_stats", "bool"),
        ("tui", "confirm_delete", "bool"),
        ("tui", "show_import_preview", "bool"),
    ]
    while True:
        items = []
        for section, key, field_type in field_specs:
            value = config.get(section, {}).get(key)
            if isinstance(value, list):
                display = ",".join(str(item) for item in value)
            else:
                display = str(value)
            items.append((f"{key}: {display}", section.upper(), COLORS["accent"] if section == "srs" else COLORS["info"]))
        choice = select_from_list(
            stdscr,
            "Settings",
            items,
            footer="[Enter] Edit  [r] Reset defaults  [q] Save & back",
            extra_bindings=[("r", "Reset defaults")],
            searchable=True,
        )
        if choice is None:
            save_config(config)
            return load_config()
        if isinstance(choice, tuple):
            if choice[1] == "r":
                config = reset_config()
            continue
        section, key, field_type = field_specs[choice]
        current = config.setdefault(section, {}).get(key)
        if field_type == "bool":
            config[section][key] = not bool(current)
            continue
        initial = ",".join(str(item) for item in current) if isinstance(current, list) else str(current)
        value = text_input(stdscr, f"{key}: ", initial=initial, y=0, x=0)
        if value is None:
            continue
        if field_type == "float":
            try:
                config[section][key] = float(value)
            except ValueError:
                show_message(stdscr, "Settings", ["Invalid number."], "error")
        elif field_type == "int":
            try:
                config[section][key] = int(value)
            except ValueError:
                show_message(stdscr, "Settings", ["Invalid integer."], "error")
        elif field_type == "list":
            config[section][key] = [part.strip() for part in value.split(",") if part.strip()]


def _forecast_counts(cards: list[dict], days: int = 7) -> list[tuple[date, int]]:
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


def _stats_pages(valid_statuses: list[dict], config: dict) -> list[tuple[str, list[str]]]:
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
    due = len(cards_due(all_cards))
    suspended = len([card for card in all_cards if card.get("suspended")])
    leech = len([card for card in all_cards if is_leech(card, config)])
    overdue_bucket = {
        "today": len([card for card in active if overdue_days(card) == 0 and card_status(card)[0].startswith("Due")]),
        "1-7d": len([card for card in active if 1 <= overdue_days(card) <= 7]),
        "8-30d": len([card for card in active if 8 <= overdue_days(card) <= 30]),
        "30+d": len([card for card in active if overdue_days(card) > 30]),
    }
    grades = grade_counts(all_cards)
    total_reviews = sum(grades.values())
    correct = grades["hard"] + grades["good"] + grades["easy"]
    retention = (correct / total_reviews * 100) if total_reviews else 0.0
    recent_cards = len([card for card in all_cards if created_within_days(card, 7)])
    avg_ease = sum(card.get("ease_factor", 2.5) for card in all_cards) / len(all_cards)
    forecast = _forecast_counts(all_cards, 7)
    overview = [
        f"Deck files: {len(valid_statuses)}",
        f"Sets: {len(set_rows)}",
        f"Cards: {len(all_cards)} total | {len(active)} active | {suspended} suspended",
        f"Due now: {due} | Leech candidates: {leech} | Added in 7d: {recent_cards}",
        f"Average ease: {avg_ease:.2f} | Retention: {retention:.1f}%",
        "",
        f"Grades -> Again {grades['again']} | Hard {grades['hard']} | Good {grades['good']} | Easy {grades['easy']}",
        "Overdue buckets",
        f"Due today: {overdue_bucket['today']}",
        f"1-7 days overdue: {overdue_bucket['1-7d']}",
        f"8-30 days overdue: {overdue_bucket['8-30d']}",
        f"30+ days overdue: {overdue_bucket['30+d']}",
    ]
    forecast_lines = []
    max_count = max((count for _, count in forecast), default=1) or 1
    for target, count in forecast:
        width = 20
        blocks = "█" * round(count / max_count * width) if count else ""
        forecast_lines.append(f"{target.strftime('%a %d/%m')}: {blocks} {count}")
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
        ("Workload", workload_lines),
    ]


def stats_screen(stdscr, config: dict) -> None:
    valid_statuses = [status for status in list_sko_files(config) if status["valid"]]
    if not valid_statuses:
        show_message(stdscr, "Statistics", ["No valid decks yet. Create one to get started."], "muted")
        return
    pages = _stats_pages(valid_statuses, config)
    page_index = 0
    while True:
        stdscr.erase()
        title, lines = pages[page_index]
        add_line(stdscr, 0, 0, f"Statistics | {title} ({page_index + 1}/{len(pages)})", curses.color_pair(COLORS["prompt"]))
        for idx, line in enumerate(lines[: stdscr.getmaxyx()[0] - 3], start=2):
            add_line(stdscr, idx, 0, line)
        add_line(stdscr, stdscr.getmaxyx()[0] - 1, 0, "[j/k] Next/prev page  [q] Back", curses.color_pair(COLORS["muted"]))
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27):
            return
        if key in (ord("j"), curses.KEY_RIGHT):
            page_index = (page_index + 1) % len(pages)
        elif key in (ord("k"), curses.KEY_LEFT):
            page_index = (page_index - 1) % len(pages)


def load_csv_headers(filepath: str) -> list[str]:
    with open(filepath, "r", newline="") as fhand:
        reader = csv.DictReader(fhand)
        return reader.fieldnames or []


def csv_mapping_screen(stdscr, filepath: str) -> dict | None:
    headers = load_csv_headers(filepath)
    if not headers:
        raise ValueError("CSV file has no header row.")
    fields = [
        "set_name",
        "card_name",
        "card_info",
        "card_add_info",
        "card_date",
        "tags",
        "suspended",
        "ease_factor",
        "interval",
        "repetitions",
    ]
    mapping, _ = infer_csv_mapping(headers)
    while True:
        missing = [field for field in ("set_name", "card_name") if field not in mapping]
        items = []
        for field in fields:
            current = mapping.get(field, "(unmapped)")
            color = COLORS["error"] if field in missing else COLORS["info"]
            items.append((field, current, color))
        footer = "[Enter] Edit field  [i] Import  [a] Auto-map  [q] Cancel"
        choice = select_from_list(
            stdscr,
            f"CSV field mapping | missing: {', '.join(missing) or 'none'}",
            items,
            footer=footer,
            extra_bindings=[("i", "Import"), ("a", "Auto-map")],
        )
        if choice is None:
            return None
        if isinstance(choice, tuple):
            if choice[1] == "a":
                mapping, _ = infer_csv_mapping(headers)
                continue
            if choice[1] == "i":
                if missing:
                    show_message(stdscr, "CSV mapping", [f"Map required fields first: {', '.join(missing)}"], "error")
                    continue
                return mapping
            continue
        field = fields[choice]
        options = [(header, "", COLORS["info"]) for header in headers]
        if field not in ("set_name", "card_name"):
            options.append(("(skip)", "", COLORS["muted"]))
        selected = select_from_list(
            stdscr,
            f"Map {field}",
            options,
            footer="[Enter] Select  [q] Back",
            searchable=True,
        )
        if selected is None:
            continue
        if selected == len(headers) and field not in ("set_name", "card_name"):
            mapping.pop(field, None)
        else:
            mapping[field] = headers[selected]


def import_screen(stdscr, config: dict) -> None:
    filepath = text_input(stdscr, "File path: ", y=0, x=0)
    if not filepath:
        return
    filepath = os.path.expanduser(filepath)
    if not os.path.isfile(filepath):
        show_message(stdscr, "Import", ["File not found."], "error")
        return
    try:
        csv_mapping = None
        if filepath.endswith(".txt"):
            data = import_from_txt(filepath, config)
        elif filepath.endswith(".csv"):
            csv_mapping = csv_mapping_screen(stdscr, filepath)
            if csv_mapping is None:
                return
            data = import_from_csv(filepath, config, field_mapping=csv_mapping)
        elif filepath.endswith(".json") or filepath.endswith(".sko"):
            data = import_from_json(filepath, config)
        else:
            raise ValueError("Unsupported file type. Use .txt, .csv, .json, or .sko.")
    except (ValueError, json.JSONDecodeError) as exc:
        show_message(stdscr, "Import", [str(exc)], "error")
        return
    preview = preview_import(data)
    while True:
        stdscr.erase()
        add_line(stdscr, 0, 0, "Import preview", curses.color_pair(COLORS["success"]))
        add_line(stdscr, 2, 0, f"Sets: {preview['set_count']} | Cards: {preview['card_count']}")
        row = 4
        for set_name, count in preview["sets"][:10]:
            add_line(stdscr, row, 0, f"{set_name}: {count} cards")
            row += 1
        if filepath.endswith(".csv") and csv_mapping:
            row += 1
            add_line(stdscr, row, 0, "CSV mapping:", curses.color_pair(COLORS["accent"]))
            row += 1
            for field, source in csv_mapping.items():
                add_line(stdscr, row, 0, f"{field} <- {source}")
                row += 1
                if row >= stdscr.getmaxyx()[0] - 3:
                    break
        add_line(
            stdscr,
            stdscr.getmaxyx()[0] - 1,
            0,
            "[n] New deck  [e] Merge  [r] Replace sets  [q] Cancel",
            curses.color_pair(COLORS["muted"]),
        )
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27):
            return
        if key == ord("n"):
            name = text_input(stdscr, "Filename: ", y=0, x=0)
            if name:
                filename = create_sko_file(name, config)
                write_sko(filename, data, config)
                show_message(stdscr, "Import", [f"Saved {preview['card_count']} cards to {filename}."], "success")
            return
        if key in (ord("e"), ord("r")):
            target = select_sko_file(stdscr, config)
            if not target:
                return
            existing = read_sko(target, config)
            target_preview = preview_import(data, existing)
            if key == ord("r"):
                merged, summary = merge_sets(existing, data, "replace_set")
            else:
                stdscr.erase()
                add_line(
                    stdscr,
                    0,
                    0,
                    f"Target preview | duplicates: {target_preview['duplicate_count']}",
                    curses.color_pair(COLORS["prompt"]),
                )
                add_line(stdscr, 2, 0, "[s] Skip dupes  [p] Replace dupes  [k] Keep all", curses.color_pair(COLORS["muted"]))
                stdscr.refresh()
                strategy_key = wait_for_keys(stdscr, (ord("s"), ord("p"), ord("k"), ord("q"), ord("Q"), 27))
                if strategy_key in (ord("q"), ord("Q"), 27):
                    return
                strategy = "skip" if strategy_key == ord("s") else "replace" if strategy_key == ord("p") else "keep"
                merged, summary = merge_sets(existing, data, strategy)
            write_sko(target, merged, config)
            show_message(
                stdscr,
                "Import",
                [
                    f"Updated {target}.",
                    f"Added: {summary['added']}",
                    f"Replaced duplicates: {summary['replaced']}",
                    f"Skipped duplicates: {summary['skipped']}",
                    f"Replaced sets: {summary['replaced_sets']}",
                ],
                "success",
            )
            return


def export_screen(stdscr, config: dict) -> None:
    filename = select_sko_file(stdscr, config)
    if not filename:
        return
    data = read_sko(filename, config)
    n_cards = sum(len(cards) for cards in data.values())
    base = os.path.splitext(filename)[0]
    stdscr.erase()
    add_line(stdscr, 0, 0, f"{filename}: {n_cards} cards", curses.color_pair(COLORS["success"]))
    add_line(stdscr, 2, 0, "[j] JSON  [t] Text  [c] CSV  [q] Cancel", curses.color_pair(COLORS["prompt"]))
    stdscr.refresh()
    while True:
        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27):
            return
        if key in (ord("j"), ord("t"), ord("c")):
            ext = ".json" if key == ord("j") else ".txt" if key == ord("t") else ".csv"
            path = text_input(
                stdscr,
                "Output path: ",
                initial=os.path.expanduser(f"~/Desktop/{base}{ext}"),
                y=0,
                x=0,
            )
            if not path:
                return
            path = os.path.expanduser(path)
            if key == ord("j"):
                export_to_json(data, path, config)
            elif key == ord("t"):
                export_to_txt(data, path)
            else:
                export_to_csv(data, path)
            show_message(stdscr, "Export", [f"Exported {n_cards} cards to {path}."], "success")
            return


def deck_screen(stdscr, filename: str, config: dict, direct_review: bool = False) -> None:
    sets = read_sko(filename, config)
    while True:
        selection = select_flashcard_set(stdscr, sets, filename, config)
        if selection is None:
            return
        set_name, cards = selection
        if direct_review:
            _, cards = render_sko_loop(stdscr, set_name, cards, config)
            sets[set_name] = cards
            write_sko(filename, sets, config)
            return
        action = select_from_list(
            stdscr,
            set_name,
            [
                ("Review", "", COLORS["accent"]),
                ("Manage cards", "", COLORS["info"]),
                ("Back to sets", "", COLORS["muted"]),
            ],
            footer="[Enter] Select  [q] Back",
        )
        if action is None or action == 2:
            continue
        if action == 0:
            _, cards = render_sko_loop(stdscr, set_name, cards, config)
            sets[set_name] = cards
        else:
            set_name, sets = manage_cards_loop(stdscr, sets, set_name, config)
        write_sko(filename, sets, config)


def menu_sko(stdscr) -> None:
    ensure_config_dir()
    config = load_config()
    menu_items = [
        ("Review cards", "", COLORS["accent"]),
        ("Browse decks", "", COLORS["info"]),
        ("Import cards", "", COLORS["success"]),
        ("Export cards", "", COLORS["success"]),
        ("Statistics", "", COLORS["muted"]),
        ("Settings", "", COLORS["prompt"]),
        ("Quit", "", COLORS["error"]),
    ]
    while True:
        choice = select_from_list(
            stdscr,
            "Senko flashcards",
            menu_items,
            footer="Spot issues? Ping me on Github @gongahkia.",
        )
        if choice is None or choice == 6:
            return
        if choice == 0:
            filename = select_sko_file(stdscr, config)
            if filename:
                deck_screen(stdscr, filename, config, direct_review=True)
        elif choice == 1:
            filename = select_sko_file(stdscr, config)
            if filename:
                deck_screen(stdscr, filename, config)
        elif choice == 2:
            import_screen(stdscr, config)
        elif choice == 3:
            export_screen(stdscr, config)
        elif choice == 4:
            stats_screen(stdscr, config)
        elif choice == 5:
            config = config_editor(stdscr, config)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    if argv:
        result = run_cli(argv)
        if result != -1:
            return result
    run_app(menu_sko)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
