from __future__ import annotations

import curses
import os
from datetime import datetime

from deck_screens import add_line, confirm_prompt, show_message
from history import archive_history, export_history, load_history, prune_history, rebuild_history
from tui import COLORS, text_input


def _history_lines(events: list[dict], page_index: int, page_size: int = 10) -> list[str]:
    newest_first = list(reversed(events))
    start = page_index * page_size
    end = start + page_size
    lines = []
    for event in newest_first[start:end]:
        timestamp = event.get("timestamp", "?")
        deck_name = event.get("deck_name", "?")
        set_name = event.get("set_name", "?")
        card_name = event.get("after", {}).get("card_name", "?")
        grade = event.get("grade", "?")
        session_mode = event.get("session_mode", "?")
        lines.append(f"{timestamp} | {deck_name}::{set_name}")
        lines.append(f"  {card_name} | grade {grade} | {session_mode}")
    return lines


def _format_from_path(path: str) -> str:
    return "json" if path.lower().endswith(".json") else "jsonl"


def _filters_label(filters: dict) -> str:
    parts = []
    if filters["deck_name"]:
        parts.append(f"deck={filters['deck_name']}")
    if filters["set_name"]:
        parts.append(f"set={filters['set_name']}")
    if filters["card_id"]:
        parts.append(f"card={filters['card_id']}")
    return ", ".join(parts) if parts else "all events"


def _prompt_filters(stdscr, filters: dict) -> dict | None:
    deck_name = text_input(stdscr, "Deck (.sko optional, blank for all): ", initial=filters["deck_name"] or "", y=0, x=0)
    if deck_name is None:
        return None
    set_name = text_input(stdscr, "Set (blank for all): ", initial=filters["set_name"] or "", y=0, x=0)
    if set_name is None:
        return None
    card_id = text_input(stdscr, "Card id (blank for all): ", initial=filters["card_id"] or "", y=0, x=0)
    if card_id is None:
        return None
    normalized_deck = deck_name.strip()
    if normalized_deck and not normalized_deck.endswith(".sko"):
        normalized_deck += ".sko"
    return {
        "deck_name": normalized_deck or None,
        "set_name": set_name.strip() or None,
        "card_id": card_id.strip() or None,
    }


def show_history_screen(stdscr, config: dict) -> None:
    page_index = 0
    page_size = 10
    filters = {"deck_name": None, "set_name": None, "card_id": None}
    while True:
        events = load_history(**filters)
        if not events:
            show_message(stdscr, "History", [f"No history for {_filters_label(filters)}."], "muted")
            filters = {"deck_name": None, "set_name": None, "card_id": None}
            continue
        page_count = max(1, (len(events) + page_size - 1) // page_size)
        page_index = min(page_index, page_count - 1)
        stdscr.erase()
        add_line(
            stdscr,
            0,
            0,
            f"History ({page_index + 1}/{page_count}) | {len(events)} events | {_filters_label(filters)}",
            curses.color_pair(COLORS["prompt"]),
        )
        row = 2
        for line in _history_lines(events, page_index, page_size):
            if row >= stdscr.getmaxyx()[0] - 2:
                break
            add_line(stdscr, row, 0, line)
            row += 1
        footer = "[j/k] Next/prev  [f] Filter  [c] Clear  [e] Export  [a] Archive  [p] Prune  [r] Rebuild  [q] Back"
        add_line(stdscr, stdscr.getmaxyx()[0] - 1, 0, footer, curses.color_pair(COLORS["muted"]))
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27):
            return
        if key in (ord("j"), curses.KEY_RIGHT):
            page_index = (page_index + 1) % page_count
            continue
        if key in (ord("k"), curses.KEY_LEFT):
            page_index = (page_index - 1) % page_count
            continue
        if key == ord("f"):
            updated_filters = _prompt_filters(stdscr, filters)
            if updated_filters is not None:
                filters = updated_filters
                page_index = 0
            continue
        if key == ord("c"):
            filters = {"deck_name": None, "set_name": None, "card_id": None}
            page_index = 0
            continue
        if key == ord("e"):
            default_path = os.path.expanduser(
                f"~/Desktop/senko-history-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
            )
            path = text_input(stdscr, "Export path: ", initial=default_path, y=0, x=0)
            if path:
                path = os.path.expanduser(path)
                result = export_history(path, format=_format_from_path(path), **filters)
                show_message(stdscr, "History", [f"Exported {result['exported']} events to {result['destination']}."], "success")
            continue
        if key == ord("a"):
            default_path = os.path.expanduser(
                f"~/Desktop/senko-history-archive-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
            )
            path = text_input(stdscr, "Archive path: ", initial=default_path, y=0, x=0)
            if path and confirm_prompt(stdscr, f"Archive history for {_filters_label(filters)} to this file?"):
                path = os.path.expanduser(path)
                result = archive_history(path, format=_format_from_path(path), **filters)
                show_message(
                    stdscr,
                    "History",
                    [f"Archived {result['archived']} events to {result['destination']}."],
                    "success",
                )
                page_index = 0
            continue
        if key == ord("p"):
            if confirm_prompt(stdscr, f"Delete history for {_filters_label(filters)}?"):
                result = prune_history(**filters)
                show_message(stdscr, "History", [f"Removed {result['removed']} history events."], "success")
                page_index = 0
            continue
        if key == ord("r"):
            if confirm_prompt(stdscr, "Rebuild history and drop malformed lines?"):
                result = rebuild_history()
                show_message(
                    stdscr,
                    "History",
                    [f"Rebuilt history with {result['events']} events and dropped {result['dropped_lines']} bad lines."],
                    "success",
                )
                page_index = 0
