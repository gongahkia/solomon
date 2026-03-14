from __future__ import annotations

import curses
import os
from datetime import datetime

from history import archive_history, export_history, load_history, prune_history, rebuild_history
from screen_common import add_line, confirm_prompt, show_message
from tui import COLORS, text_input


def _page_events(events: list[dict], page_index: int, page_size: int = 5) -> list[dict]:
    newest_first = list(reversed(events))
    start = page_index * page_size
    end = start + page_size
    return newest_first[start:end]


def _event_summary(event: dict) -> tuple[str, str]:
    before = event.get("before", {})
    after = event.get("after", {})
    header = f"{event.get('timestamp', '?')} | {event.get('deck_name', '?')}::{event.get('set_name', '?')}"
    detail = (
        f"{after.get('card_name', '?')} | grade {event.get('grade', '?')} | {event.get('session_mode', '?')} | "
        f"int {before.get('interval', 0)}->{after.get('interval', 0)} | ease "
        f"{before.get('ease_factor', 0.0)}->{after.get('ease_factor', 0.0)}"
    )
    return header, detail


def _event_detail_lines(event: dict) -> list[str]:
    before = event.get("before", {})
    after = event.get("after", {})
    return [
        f"Timestamp: {event.get('timestamp', '?')}",
        f"Deck: {event.get('deck_name', '?')}",
        f"Set: {event.get('set_name', '?')}",
        f"Card: {after.get('card_name', '?')}",
        f"Card id: {after.get('card_id', '?')}",
        f"Mode: {event.get('session_mode', '?')}",
        f"Grade: {event.get('grade', '?')}",
        f"State: {before.get('state', 'new')} -> {after.get('state', 'new')}",
        f"Step index: {before.get('step_index', 0)} -> {after.get('step_index', 0)}",
        f"Interval: {before.get('interval', 0)} -> {after.get('interval', 0)}",
        f"Ease factor: {before.get('ease_factor', 0.0)} -> {after.get('ease_factor', 0.0)}",
        f"Repetitions: {before.get('repetitions', 0)} -> {after.get('repetitions', 0)}",
        f"Lapses: {before.get('lapses', 0)} -> {after.get('lapses', 0)}",
        f"Suspended: {before.get('suspended', False)} -> {after.get('suspended', False)}",
    ]


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


def show_history_screen(stdscr, _config: dict) -> None:
    page_index = 0
    page_size = 5
    selected_index = 0
    filters = {"deck_name": None, "set_name": None, "card_id": None}
    while True:
        events = load_history(**filters)
        if not events:
            if any(filters.values()):
                show_message(stdscr, "History", [f"No history for {_filters_label(filters)}. Clearing filters."], "muted")
                filters = {"deck_name": None, "set_name": None, "card_id": None}
                page_index = 0
                continue
            show_message(stdscr, "History", ["No review history yet."], "muted")
            return
        page_count = max(1, (len(events) + page_size - 1) // page_size)
        page_index = min(page_index, page_count - 1)
        page_events = _page_events(events, page_index, page_size)
        selected_index = min(selected_index, len(page_events) - 1)
        stdscr.erase()
        add_line(
            stdscr,
            0,
            0,
            f"History ({page_index + 1}/{page_count}) | {len(events)} events | {_filters_label(filters)}",
            curses.color_pair(COLORS["prompt"]),
        )
        row = 2
        for index, event in enumerate(page_events):
            if row >= stdscr.getmaxyx()[0] - 3:
                break
            header, detail = _event_summary(event)
            prefix = ">" if index == selected_index else " "
            attr = curses.color_pair(COLORS["accent"]) if index == selected_index else 0
            add_line(stdscr, row, 0, f"{prefix} {header}", attr)
            row += 1
            add_line(stdscr, row, 0, f"  {detail}")
            row += 1
        footer = "[j/k] Move  [h/l] Page  [Enter] Detail  [f] Filter  [c] Clear  [e] Export  [a] Archive  [p] Prune  [r] Rebuild  [q] Back"
        add_line(stdscr, stdscr.getmaxyx()[0] - 1, 0, footer, curses.color_pair(COLORS["muted"]))
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27):
            return
        if key in (ord("j"), curses.KEY_DOWN):
            if selected_index + 1 < len(page_events):
                selected_index += 1
            elif page_index + 1 < page_count:
                page_index += 1
                selected_index = 0
            continue
        if key in (ord("k"), curses.KEY_UP):
            if selected_index > 0:
                selected_index -= 1
            elif page_index > 0:
                page_index -= 1
                previous_page_events = _page_events(events, page_index, page_size)
                selected_index = max(0, len(previous_page_events) - 1)
            continue
        if key in (ord("l"), curses.KEY_RIGHT):
            page_index = (page_index + 1) % page_count
            selected_index = 0
            continue
        if key in (ord("h"), curses.KEY_LEFT):
            page_index = (page_index - 1) % page_count
            selected_index = 0
            continue
        if key in (10, 13, ord("v"), ord("V"), ord(" ")):
            event = page_events[selected_index]
            show_message(stdscr, "History event", _event_detail_lines(event), "info")
            continue
        if key == ord("f"):
            updated_filters = _prompt_filters(stdscr, filters)
            if updated_filters is not None:
                filters = updated_filters
                page_index = 0
                selected_index = 0
            continue
        if key == ord("c"):
            filters = {"deck_name": None, "set_name": None, "card_id": None}
            page_index = 0
            selected_index = 0
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
                selected_index = 0
            continue
        if key == ord("p"):
            if confirm_prompt(stdscr, f"Delete history for {_filters_label(filters)}?"):
                result = prune_history(**filters)
                show_message(stdscr, "History", [f"Removed {result['removed']} history events."], "success")
                page_index = 0
                selected_index = 0
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
                selected_index = 0
