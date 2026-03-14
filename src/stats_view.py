from __future__ import annotations

import curses

from analytics import stats_pages
from history import load_history
from tui import COLORS


def _add_line(stdscr, y: int, x: int, text: str, attr: int = 0) -> None:
    max_x = stdscr.getmaxyx()[1]
    if y < 0 or x >= max_x:
        return
    try:
        stdscr.addstr(y, x, text[: max_x - x - 1], attr)
    except curses.error:
        pass


def show_stats_screen(stdscr, valid_statuses: list[dict], config: dict) -> None:
    if not valid_statuses:
        stdscr.erase()
        _add_line(stdscr, 0, 0, "Statistics", curses.color_pair(COLORS["prompt"]))
        _add_line(stdscr, 2, 0, "No valid decks yet. Create one to get started.", curses.color_pair(COLORS["muted"]))
        _add_line(stdscr, stdscr.getmaxyx()[0] - 1, 0, "[q] Back", curses.color_pair(COLORS["muted"]))
        stdscr.refresh()
        while stdscr.getch() not in (ord("q"), ord("Q"), 27):
            pass
        return
    pages = stats_pages(valid_statuses, load_history(), config)
    page_index = 0
    while True:
        stdscr.erase()
        title, lines = pages[page_index]
        _add_line(stdscr, 0, 0, f"Statistics | {title} ({page_index + 1}/{len(pages)})", curses.color_pair(COLORS["prompt"]))
        for idx, line in enumerate(lines[: stdscr.getmaxyx()[0] - 3], start=2):
            _add_line(stdscr, idx, 0, line)
        _add_line(stdscr, stdscr.getmaxyx()[0] - 1, 0, "[j/k] Next/prev page  [q] Back", curses.color_pair(COLORS["muted"]))
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27):
            return
        if key in (ord("j"), curses.KEY_RIGHT):
            page_index = (page_index + 1) % len(pages)
        elif key in (ord("k"), curses.KEY_LEFT):
            page_index = (page_index - 1) % len(pages)
