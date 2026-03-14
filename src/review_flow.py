from __future__ import annotations

import curses

from deck_ops import card_detail, card_status
from review_session import (
    apply_review,
    next_due_text,
    review_summary_lines,
    start_session,
    undo_last_review,
)
from screen_common import add_line, show_message
from schema import is_leech, touch_card
from srs import active_cards, cards_due
from tui import COLORS, select_from_list


def _review_mode_screen(stdscr, set_name: str, cards: list[dict]) -> str | None:
    reviewable = active_cards(cards)
    due = cards_due(cards)
    if not reviewable:
        show_message(stdscr, set_name, ["All cards in this set are suspended."], "muted")
        return None
    if not due:
        next_date = next_due_text(cards)
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


def _draw_card_back(stdscr, set_name: str, card: dict, index: int, total_cards: int, config: dict) -> int:
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


def _maybe_handle_leech(stdscr, card: dict, config: dict) -> None:
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
        show_message(stdscr, set_name, ["This set is empty. Add cards before reviewing."], "muted")
        return (set_name, cards)
    review_mode = _review_mode_screen(stdscr, set_name, cards)
    if review_mode is None:
        return (set_name, cards)
    session = start_session(cards, review_mode)
    review_cards = session["review_cards"]
    if not review_cards:
        show_message(
            stdscr,
            set_name,
            [f"All caught up. Next review: {next_due_text(cards)}"],
            "success",
        )
        return (set_name, cards)
    index = 0
    while index < len(review_cards):
        card = review_cards[index]
        front_key = _draw_card_front(stdscr, set_name, card, index, len(review_cards), bool(session["history"]), config)
        if front_key in (ord("q"), ord("Q")):
            break
        if front_key in (ord("u"), ord("U")) and session["history"]:
            undo_last_review(session, deck_name=deck_name, set_name=set_name)
            index = max(0, index - 1)
            continue
        back_key = _draw_card_back(stdscr, set_name, card, index, len(review_cards), config)
        if back_key in (ord("q"), ord("Q")):
            break
        grade = int(chr(back_key)) - 1
        apply_review(
            session,
            deck_name=deck_name,
            set_name=set_name,
            card=card,
            grade=grade,
            config=config,
            leech_handler=lambda card_obj, cfg: _maybe_handle_leech(stdscr, card_obj, cfg),
        )
        index += 1
    show_message(
        stdscr,
        set_name,
        review_summary_lines(session, cards),
        "success",
    )
    return (set_name, cards)
