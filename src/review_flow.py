from __future__ import annotations

import curses
import time
from copy import deepcopy

from deck_ops import card_detail, card_status, restore_card
from history import log_review_event
from schema import is_leech, touch_card
from srs import active_cards, cards_due, cards_due_count, next_review_date, sm2_review
from tui import COLORS


def _add_line(stdscr, y: int, x: int, text: str, attr: int = 0) -> None:
    max_x = stdscr.getmaxyx()[1]
    if y < 0 or x >= max_x:
        return
    try:
        stdscr.addstr(y, x, text[: max_x - x - 1], attr)
    except curses.error:
        pass


def _show_message(stdscr, title: str, lines: list[str], color_key: str = "info") -> None:
    stdscr.erase()
    _add_line(stdscr, 0, 0, title, curses.color_pair(COLORS[color_key]))
    for index, line in enumerate(lines, start=2):
        _add_line(stdscr, index, 0, line)
    _add_line(stdscr, stdscr.getmaxyx()[0] - 1, 0, "[q] Back", curses.color_pair(COLORS["muted"]))
    stdscr.refresh()
    while True:
        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27, 10, 13):
            return


def _review_mode_screen(stdscr, set_name: str, cards: list[dict]) -> str | None:
    from tui import select_from_list

    reviewable = active_cards(cards)
    due = cards_due(cards)
    if not reviewable:
        _show_message(stdscr, set_name, ["All cards in this set are suspended."], "muted")
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


def _draw_card_front(stdscr, set_name: str, card: dict, index: int, total_cards: int, can_undo: bool, config: dict) -> int:
    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()
        detail, color = card_detail(card, config)
        _add_line(stdscr, 0, 0, set_name, curses.color_pair(COLORS["accent"]))
        _add_line(stdscr, 0, max(0, max_x - 12), f"{index + 1}/{total_cards}")
        _add_line(stdscr, 1, 0, detail, curses.color_pair(color))
        center_y = max_y // 2
        name = card.get("card_name", "")
        _add_line(stdscr, center_y, max(0, (max_x - len(name)) // 2), name, curses.A_BOLD)
        footer = "[Space] Show answer  [q] Quit session"
        if can_undo:
            footer += "  [u] Undo last"
        _add_line(stdscr, max_y - 1, 0, footer, curses.color_pair(COLORS["muted"]))
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord(" "), 10, 13, ord("q"), ord("Q"), ord("u"), ord("U")):
            return key


def _draw_card_back(stdscr, set_name: str, card: dict, index: int, total_cards: int, config: dict) -> int:
    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()
        _add_line(stdscr, 0, 0, card.get("card_name", ""), curses.A_BOLD)
        _add_line(stdscr, 0, max(0, max_x - 12), f"{index + 1}/{total_cards}")
        status, color = card_status(card)
        extra = f"{set_name} | {status} | {card.get('state', 'new')}"
        if is_leech(card, config):
            extra += " | leech"
        _add_line(stdscr, 1, 0, extra, curses.color_pair(color))
        row = 3
        for line in card.get("card_info", "").splitlines() or [""]:
            _add_line(stdscr, row, 0, line)
            row += 1
        add_info = card.get("card_add_info", "")
        if add_info:
            row += 1
            for line in add_info.splitlines():
                _add_line(stdscr, row, 0, line, curses.color_pair(COLORS["muted"]))
                row += 1
        tags = card.get("tags", [])
        if tags:
            _add_line(stdscr, max_y - 3, 0, f"Tags: {', '.join(tags)}", curses.color_pair(COLORS["muted"]))
        _add_line(
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


def _maybe_handle_leech(stdscr, card: dict, config: dict) -> None:
    threshold = int(config.get("srs", {}).get("leech_threshold", 8))
    if int(card.get("lapses", 0)) != threshold or card.get("suspended"):
        return
    stdscr.erase()
    _add_line(
        stdscr,
        0,
        0,
        f"{card.get('card_name', 'Card')} reached the leech threshold ({threshold} lapses).",
        curses.color_pair(COLORS["prompt"]),
    )
    _add_line(stdscr, 2, 0, "[s] Suspend card  [k] Keep active", curses.color_pair(COLORS["muted"]))
    stdscr.refresh()
    while True:
        key = stdscr.getch()
        if key in (ord("s"), ord("S")):
            card["suspended"] = True
            touch_card(card)
            return
        if key in (ord("k"), ord("K"), 27):
            return


def render_review_session(stdscr, deck_name: str, set_name: str, cards: list[dict], config: dict) -> tuple[str, list]:
    if not cards:
        _show_message(stdscr, set_name, ["This set is empty. Add cards before reviewing."], "muted")
        return (set_name, cards)
    review_mode = _review_mode_screen(stdscr, set_name, cards)
    if review_mode is None:
        return (set_name, cards)
    review_cards = cards_due(cards) if review_mode == "due" else active_cards(cards)
    if not review_cards:
        _show_message(
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
        front_key = _draw_card_front(stdscr, set_name, card, index, len(review_cards), bool(history), config)
        if front_key in (ord("q"), ord("Q")):
            break
        if front_key in (ord("u"), ord("U")) and history:
            last = history.pop()
            restore_card(last["card"], last["snapshot"])
            session_counts[last["grade"]] -= 1
            index = max(0, index - 1)
            continue
        before = deepcopy(card)
        back_key = _draw_card_back(stdscr, set_name, card, index, len(review_cards), config)
        if back_key in (ord("q"), ord("Q")):
            break
        grade = int(chr(back_key)) - 1
        sm2_review(card, grade, config)
        _maybe_handle_leech(stdscr, card, config)
        log_review_event(deck_name, set_name, before, card, grade, review_mode)
        session_counts[grade] += 1
        history.append({"card": card, "snapshot": before, "grade": grade})
        index += 1
    elapsed = time.time() - start_time
    reviewed = len(history)
    _show_message(
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
