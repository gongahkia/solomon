# mypy: ignore-errors

from __future__ import annotations

import curses
import json
import os
import time
from datetime import date, datetime, timedelta

from config import load_config, reset_config, save_config
from import_export import (
    count_duplicates,
    export_to_csv,
    export_to_json,
    export_to_txt,
    import_from_csv,
    import_from_json,
    import_from_txt,
    merge_sets,
)
from schema import DATE_FORMAT, new_card, reset_card_progress, touch_card
from srs import active_cards, cards_due, cards_due_count, next_review_date, sm2_review
from storage import ensure_config_dir, list_sko_files, read_sko, sko_path, write_sko
from tui import COLORS, form_input, run_app, select_from_list, text_input


def add_line(stdscr, y: int, x: int, text: str, attr: int = 0) -> None:
    max_x = stdscr.getmaxyx()[1]
    if y < 0 or x >= max_x:
        return
    try:
        stdscr.addstr(y, x, text[: max_x - x - 1], attr)
    except curses.error:
        pass


def wait_for_q(stdscr) -> None:
    while True:
        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27, 10, 13):
            return


def show_message(stdscr, title: str, lines: list[str], color_key: str = "info") -> None:
    stdscr.erase()
    add_line(stdscr, 0, 0, title, curses.color_pair(COLORS[color_key]))
    for index, line in enumerate(lines, start=2):
        add_line(stdscr, index, 0, line)
    add_line(stdscr, stdscr.getmaxyx()[0] - 1, 0, "[q] Back", curses.color_pair(COLORS["muted"]))
    stdscr.refresh()
    wait_for_q(stdscr)


def confirm_prompt(stdscr, prompt: str, color_key: str = "error") -> bool:
    stdscr.erase()
    add_line(stdscr, 0, 0, prompt, curses.color_pair(COLORS[color_key]))
    add_line(stdscr, 2, 0, "[y] Yes  [n] No", curses.color_pair(COLORS["muted"]))
    stdscr.refresh()
    while True:
        key = stdscr.getch()
        if key in (ord("y"), ord("Y")):
            return True
        if key in (ord("n"), ord("N"), 27):
            return False


def parse_tags(raw_tags: str) -> list[str]:
    return [tag.strip() for tag in raw_tags.split(",") if tag.strip()]


def card_status(card: dict) -> tuple[str, int]:
    if card.get("suspended"):
        return ("Suspended", COLORS["muted"])
    try:
        card_date = datetime.strptime(card["card_date"], DATE_FORMAT).date()
    except (TypeError, ValueError, KeyError):
        return ("Due (invalid date)", COLORS["error"])
    if card_date <= date.today():
        return ("Due", COLORS["error"])
    return (f"Next {card_date.strftime(DATE_FORMAT)}", COLORS["success"])


def card_detail(card: dict) -> tuple[str, int]:
    status, color = card_status(card)
    tags = f" | tags: {', '.join(card.get('tags', []))}" if card.get("tags") else ""
    return (f"{status}{tags}", color)


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
        footer = "[Enter] Open  [n] New file  [d] Delete file  [/] Filter  [q] Back"
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
                if confirm_prompt(stdscr, f"Delete {filename}?"):
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
                detail_text = f"{n_due} due | {n_suspended} suspended"
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
                if confirm_prompt(stdscr, f"Delete '{set_name}'?"):
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


def draw_card_front(stdscr, set_name: str, card: dict, reviewed: int, total_cards: int) -> int:
    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()
        add_line(stdscr, 0, 0, set_name, curses.color_pair(COLORS["accent"]))
        add_line(stdscr, 0, max(0, max_x - 12), f"{reviewed}/{total_cards}")
        center_y = max_y // 2
        name = card.get("card_name", "")
        add_line(stdscr, center_y, max(0, (max_x - len(name)) // 2), name, curses.A_BOLD)
        add_line(
            stdscr,
            max_y - 1,
            0,
            "[Space] Show answer  [q] Quit session",
            curses.color_pair(COLORS["muted"]),
        )
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord(" "), ord("\n"), 10, 13):
            return key
        if key in (ord("q"), ord("Q")):
            return key


def draw_card_back(stdscr, set_name: str, card: dict, reviewed: int, total_cards: int) -> int:
    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()
        add_line(stdscr, 0, 0, card.get("card_name", ""), curses.A_BOLD)
        add_line(stdscr, 0, max(0, max_x - 12), f"{reviewed}/{total_cards}")
        status, _ = card_status(card)
        add_line(stdscr, 1, 0, f"{set_name} | {status}", curses.color_pair(COLORS["info"]))
        row = 3
        for line in card.get("card_info", "").splitlines() or [""]:
            add_line(stdscr, row, 0, line)
            row += 1
        add_info = card.get("card_add_info", "")
        if add_info:
            add_line(stdscr, row + 1, 0, add_info, curses.color_pair(COLORS["muted"]))
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
    reviewed = 0
    total_cards = len(review_cards)
    for card in review_cards:
        reviewed += 1
        front_key = draw_card_front(stdscr, set_name, card, reviewed, total_cards)
        if front_key in (ord("q"), ord("Q")):
            break
        back_key = draw_card_back(stdscr, set_name, card, reviewed, total_cards)
        if back_key in (ord("q"), ord("Q")):
            break
        sm2_review(card, int(chr(back_key)) - 1, config)
    elapsed = time.time() - start_time
    show_message(
        stdscr,
        set_name,
        [
            f"Reviewed {reviewed} cards in {elapsed / 60:.1f} minutes.",
            f"Remaining due today: {cards_due_count(cards)}",
        ],
        "success",
    )
    return (set_name, cards)


def edit_sko_card(stdscr, card: dict) -> dict | None:
    result = form_input(
        stdscr,
        "Edit card",
        [
            ("Name", card.get("card_name", "")),
            ("Info", card.get("card_info", "")),
            ("Additional info", card.get("card_add_info", "")),
            ("Tags", ",".join(card.get("tags", []))),
        ],
    )
    if result is None or not result[0].strip():
        return None
    card["card_name"] = result[0]
    card["card_info"] = result[1]
    card["card_add_info"] = result[2]
    card["tags"] = parse_tags(result[3])
    touch_card(card)
    return card


def add_sko_card(stdscr, config: dict) -> dict | None:
    result = form_input(
        stdscr,
        "Add new card",
        [
            ("Name", ""),
            ("Info", ""),
            ("Additional info", ""),
            ("Tags", ""),
        ],
    )
    if result is None or not result[0].strip():
        return None
    return new_card(
        card_name=result[0],
        card_info=result[1],
        card_add_info=result[2],
        tags=parse_tags(result[3]),
        config=config,
    )


def manage_cards_loop(stdscr, set_name: str, cards: list[dict], config: dict) -> tuple[str, list]:
    while True:
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
            return (set_name, cards)
        items = []
        for card in cards:
            detail, color = card_detail(card)
            items.append((card.get("card_name", "?"), detail, color))
        choice = select_from_list(
            stdscr,
            f"Manage cards in {set_name}",
            items,
            footer="[Enter] Open  [a] Add card  [/] Filter  [q] Back",
            extra_bindings=[("a", "Add card")],
            searchable=True,
        )
        if choice is None:
            return (set_name, cards)
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
                (suspend_label, "", COLORS["muted"]),
                ("Reset progress", f"Interval: {card.get('interval', 0)}", COLORS["prompt"]),
                ("Delete", "", COLORS["error"]),
                ("Back", "", COLORS["muted"]),
            ],
            footer="[Enter] Select  [q] Back",
        )
        if action is None or action == 4:
            continue
        if action == 0:
            updated = edit_sko_card(stdscr, card)
            if updated is not None:
                cards[choice] = updated
        elif action == 1:
            card["suspended"] = not card.get("suspended", False)
            touch_card(card)
        elif action == 2:
            reset_card_progress(card, config)
        elif action == 3:
            if confirm_prompt(stdscr, f"Delete '{card.get('card_name', '?')}'?"):
                del cards[choice]


def config_editor(stdscr, config: dict) -> dict:
    while True:
        srs = config.get("srs", {})
        tui = config.get("tui", {})
        items = [
            (f"Initial ease: {srs.get('initial_ease', 2.5)}", "SRS", COLORS["accent"]),
            (f"Minimum ease: {srs.get('minimum_ease', 1.3)}", "SRS", COLORS["accent"]),
            (f"Easy bonus: {srs.get('easy_bonus', 1.3)}", "SRS", COLORS["accent"]),
            (f"Hard factor: {srs.get('hard_factor', 0.8)}", "SRS", COLORS["accent"]),
            (f"Show stats: {tui.get('show_stats', True)}", "TUI", COLORS["info"]),
            (f"Confirm delete: {tui.get('confirm_delete', True)}", "TUI", COLORS["info"]),
        ]
        choice = select_from_list(
            stdscr,
            "Settings",
            items,
            footer="[Enter] Edit  [r] Reset defaults  [q] Save & back",
            extra_bindings=[("r", "Reset defaults")],
        )
        if choice is None:
            save_config(config)
            return config
        if isinstance(choice, tuple):
            if choice[1] == "r":
                config = reset_config()
            continue
        if choice < 4:
            keys = ["initial_ease", "minimum_ease", "easy_bonus", "hard_factor"]
            key = keys[choice]
            value = text_input(stdscr, f"{key}: ", initial=str(srs.get(key, "")), y=0, x=0)
            if value is not None:
                try:
                    config.setdefault("srs", {})[key] = float(value)
                except ValueError:
                    show_message(stdscr, "Settings", ["Invalid number."], "error")
        else:
            keys = ["show_stats", "confirm_delete"]
            key = keys[choice - 4]
            config.setdefault("tui", {})[key] = not tui.get(key, True)


def stats_screen(stdscr, config: dict) -> None:
    valid_statuses = [status for status in list_sko_files(config) if status["valid"]]
    if not valid_statuses:
        show_message(stdscr, "Statistics", ["No valid decks yet. Create one to get started."], "muted")
        return
    all_cards = []
    file_stats = []
    for status in valid_statuses:
        cards = [card for set_cards in status["sets"].values() for card in set_cards]
        all_cards.extend(cards)
        file_stats.append(
            (
                status["filename"],
                len(cards),
                cards_due_count(cards),
                len([card for card in cards if card.get("suspended")]),
            )
        )
    today = date.today()
    day_counts = []
    for offset in range(7):
        target = today + timedelta(days=offset)
        count = 0
        for card in active_cards(all_cards):
            try:
                card_date = datetime.strptime(card["card_date"], DATE_FORMAT).date()
                if card_date == target:
                    count += 1
            except (TypeError, ValueError, KeyError):
                if offset == 0:
                    count += 1
        day_counts.append((target, count))
    avg_ease = sum(card.get("ease_factor", 2.5) for card in all_cards) / len(all_cards)
    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()
        add_line(stdscr, 0, 0, "Statistics", curses.color_pair(COLORS["prompt"]))
        row = 2
        for filename, total, due, suspended in file_stats:
            if row >= max_y - 10:
                break
            add_line(
                stdscr,
                row,
                0,
                f"{filename}: {total} cards | {due} due | {suspended} suspended",
                curses.color_pair(COLORS["info"]),
            )
            row += 1
        row += 1
        add_line(stdscr, row, 0, "7-day forecast", curses.color_pair(COLORS["accent"]))
        row += 1
        max_count = max((count for _, count in day_counts), default=1) or 1
        bar_width = max(10, max_x - 20)
        for target, count in day_counts:
            if row >= max_y - 2:
                break
            blocks = "█" * round(count / max_count * bar_width) if count else ""
            add_line(stdscr, row, 0, f"{target.strftime('%a %d/%m')}: {blocks} {count}")
            row += 1
        add_line(
            stdscr,
            max_y - 1,
            0,
            f"[q] Back | Avg ease {avg_ease:.2f} | Active cards {len(active_cards(all_cards))}",
            curses.color_pair(COLORS["muted"]),
        )
        stdscr.refresh()
        if stdscr.getch() in (ord("q"), ord("Q"), 27):
            return


def import_screen(stdscr, config: dict) -> None:
    filepath = text_input(stdscr, "File path: ", y=0, x=0)
    if not filepath:
        return
    filepath = os.path.expanduser(filepath)
    if not os.path.isfile(filepath):
        show_message(stdscr, "Import", ["File not found."], "error")
        return
    try:
        if filepath.endswith(".txt"):
            data = import_from_txt(filepath, config)
        elif filepath.endswith(".csv"):
            data = import_from_csv(filepath, config)
        elif filepath.endswith(".json") or filepath.endswith(".sko"):
            data = import_from_json(filepath, config)
        else:
            raise ValueError("Unsupported file type. Use .txt, .csv, .json, or .sko.")
    except (ValueError, json.JSONDecodeError) as exc:
        show_message(stdscr, "Import", [str(exc)], "error")
        return
    n_cards = sum(len(cards) for cards in data.values())
    n_sets = len(data)
    stdscr.erase()
    add_line(stdscr, 0, 0, f"{n_cards} cards across {n_sets} sets", curses.color_pair(COLORS["success"]))
    add_line(stdscr, 2, 0, "[n] New .sko file  [e] Merge into existing  [q] Cancel", curses.color_pair(COLORS["prompt"]))
    stdscr.refresh()
    while True:
        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27):
            return
        if key == ord("n"):
            name = text_input(stdscr, "Filename: ", y=0, x=0)
            if name:
                filename = create_sko_file(name, config)
                write_sko(filename, data, config)
                show_message(stdscr, "Import", [f"Saved {n_cards} cards to {filename}."], "success")
            return
        if key == ord("e"):
            target = select_sko_file(stdscr, config)
            if not target:
                return
            existing = read_sko(target, config)
            duplicates = count_duplicates(existing, data)
            strategy = "skip"
            if duplicates:
                stdscr.erase()
                add_line(stdscr, 0, 0, f"{duplicates} duplicate card names detected in matching sets.", curses.color_pair(COLORS["prompt"]))
                add_line(stdscr, 2, 0, "[s] Skip duplicates  [r] Replace duplicates  [k] Keep all", curses.color_pair(COLORS["muted"]))
                stdscr.refresh()
                while True:
                    merge_key = stdscr.getch()
                    if merge_key == ord("s"):
                        strategy = "skip"
                        break
                    if merge_key == ord("r"):
                        strategy = "replace"
                        break
                    if merge_key == ord("k"):
                        strategy = "keep"
                        break
                    if merge_key in (ord("q"), ord("Q"), 27):
                        return
            merged, summary = merge_sets(existing, data, strategy)
            write_sko(target, merged, config)
            show_message(
                stdscr,
                "Import",
                [
                    f"Merged into {target}.",
                    f"Added: {summary['added']}",
                    f"Replaced: {summary['replaced']}",
                    f"Skipped: {summary['skipped']}",
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
        else:
            _, cards = manage_cards_loop(stdscr, set_name, cards, config)
        sets[set_name] = cards
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


run_app(menu_sko)
