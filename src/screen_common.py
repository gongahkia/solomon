from __future__ import annotations

import curses

from tui import COLORS


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
