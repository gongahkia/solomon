from __future__ import annotations

import os

from schema import is_leech
from screen_common import confirm_prompt, show_message
from srs import cards_due_count
from storage import ensure_config_dir, list_sko_files, sko_path, write_sko
from tui import COLORS, select_from_list, text_input


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
