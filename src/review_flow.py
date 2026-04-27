from __future__ import annotations

import curses
import re

from deck_ops import card_detail, card_status
from rich_content import render_rich_text
from review_session import (
    apply_review,
    downvoted_cards,
    get_vote,
    next_due_text,
    review_summary_lines,
    set_vote,
    start_session,
    undo_last_review,
)
from screen_common import add_line, show_message
from schema import is_leech, touch_card
from srs import active_cards, cards_due
from terminal_images import clear_native_images, render_native_image, terminal_supports_graphics
from tui import COLORS, select_from_list


def _style_attr(style: str) -> int:
    if style == "code_default":
        style = "default"
    color_key = style if style in COLORS else "default"
    return curses.color_pair(COLORS[color_key])


def _draw_styled_lines(
    stdscr,
    styled_lines: list[list[tuple[str, str]]],
    *,
    start_row: int,
    end_row_exclusive: int,
    default_style: str = "default",
) -> tuple[int, bool]:
    max_x = stdscr.getmaxyx()[1]
    row = start_row
    truncated = False
    for line in styled_lines:
        if row >= end_row_exclusive:
            truncated = True
            break
        col = 0
        for text, style in line:
            if col >= max_x - 1:
                break
            if style == "default":
                style = default_style
            segment = text[: max_x - col - 1]
            if not segment:
                continue
            try:
                stdscr.addstr(row, col, segment, _style_attr(style))
            except curses.error:
                pass
            col += len(segment)
        row += 1
    if truncated and row < end_row_exclusive:
        add_line(stdscr, row, 0, "...", curses.color_pair(COLORS["muted"]))
        row += 1
    return (row, truncated)


AUTO_SIZE_RE = re.compile(r"^Auto-size:\s*(\d+)x(\d+)\s*$")
GRADE_LABELS = ("Again", "Hard", "Good", "Easy")


def _mouse_event(key: int) -> str | None:
    if key != curses.KEY_MOUSE:
        return None
    try:
        _, _, _, _, button_state = curses.getmouse()
    except curses.error:
        return None

    left_events = (
        "BUTTON1_CLICKED",
    )
    right_events = (
        "BUTTON3_CLICKED",
    )
    if any(button_state & getattr(curses, event_name, 0) for event_name in left_events):
        return "left"
    if any(button_state & getattr(curses, event_name, 0) for event_name in right_events):
        return "right"
    return None


def _mouse_button(key: int) -> str | None:
    event = _mouse_event(key)
    if event in ("left", "right"):
        return event
    return None


def _grade_footer(selected_grade: int, voting_enabled: bool) -> str:
    grade_parts = []
    for index, label in enumerate(GRADE_LABELS):
        key_label = str(index + 1)
        if index == selected_grade:
            key_label += "/Left"
        grade_parts.append(f"[{key_label}] {label}")
    footer = "  ".join(grade_parts) + "  [Right Click] Change  [q] Quit session"
    if voting_enabled:
        footer += "  [+] Upvote  [-] Downvote  [0] Clear vote"
    return footer


def _parse_auto_size(line: str) -> tuple[int, int] | None:
    match = AUTO_SIZE_RE.match(line.strip())
    if not match:
        return None
    return (max(1, int(match.group(1))), max(1, int(match.group(2))))


def _native_image_enabled(config: dict) -> bool:
    if not bool(config.get("tui", {}).get("native_image_rendering", True)):
        return False
    return terminal_supports_graphics()


def _collect_native_image_requests(
    styled_lines: list[list[tuple[str, str]]],
    *,
    start_row: int,
    end_row_exclusive: int,
    default_width: int,
    default_height: int,
) -> list[dict]:
    requests = []
    row = start_row
    pending_url = None
    pending_width = default_width
    pending_height = default_height
    ready_for_preview = False
    for line in styled_lines:
        if row >= end_row_exclusive:
            break
        raw_text = "".join(text for text, _style in line)
        stripped = raw_text.strip()
        if stripped.startswith("URL: "):
            pending_url = stripped[5:].strip()
            pending_width = default_width
            pending_height = default_height
            ready_for_preview = False
        elif pending_url and stripped.startswith("Auto-size:"):
            parsed = _parse_auto_size(stripped)
            if parsed is not None:
                pending_width, pending_height = parsed
            ready_for_preview = True
        elif pending_url and stripped.startswith("Preview note:"):
            pass
        elif pending_url and stripped.startswith("Preview unavailable:"):
            pass
        elif pending_url and ready_for_preview and raw_text:
            requests.append(
                {
                    "url": pending_url,
                    "row": row,
                    "col": 0,
                    "width": pending_width,
                    "height": pending_height,
                }
            )
            pending_url = None
            ready_for_preview = False
        row += 1
    return requests


def _render_native_image_requests(stdscr, requests: list[dict], config: dict) -> None:
    if not requests or not _native_image_enabled(config):
        return
    max_y, max_x = stdscr.getmaxyx()
    for request in requests:
        row = int(request.get("row", 0))
        col = int(request.get("col", 0))
        if row >= max_y - 1 or col >= max_x - 1:
            continue
        width = max(4, min(int(request.get("width", 40)), max_x - col - 1))
        height = max(2, min(int(request.get("height", 12)), max_y - row - 2))
        render_native_image(
            str(request.get("url", "")),
            row=row,
            col=col,
            width_cells=width,
            height_cells=height,
        )


def _rich_lines(text: str, config: dict, width: int) -> list[list[tuple[str, str]]]:
    tui_config = config.get("tui", {})
    return render_rich_text(
        text,
        width=max(1, width),
        image_width=int(tui_config.get("image_width", 72)),
        image_height=int(tui_config.get("image_height", 24)),
        syntax_highlighting=bool(tui_config.get("syntax_highlighting", True)),
        render_latex=bool(tui_config.get("render_latex", True)),
        show_image_warnings=bool(tui_config.get("show_image_warnings", False)),
    )


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
        if _native_image_enabled(config):
            clear_native_images()
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()
        detail, color = card_detail(card, config)
        add_line(stdscr, 0, 0, set_name, curses.color_pair(COLORS["accent"]))
        add_line(stdscr, 0, max(0, max_x - 12), f"{index + 1}/{total_cards}")
        add_line(stdscr, 1, 0, detail, curses.color_pair(color))
        content_top = max(3, max_y // 3)
        question_lines = _rich_lines(card.get("card_name", ""), config, max_x - 1)
        image_requests = _collect_native_image_requests(
            question_lines,
            start_row=content_top,
            end_row_exclusive=max_y - 2,
            default_width=int(config.get("tui", {}).get("image_width", 72)),
            default_height=int(config.get("tui", {}).get("image_height", 24)),
        )
        _draw_styled_lines(
            stdscr,
            question_lines,
            start_row=content_top,
            end_row_exclusive=max_y - 2,
            default_style="default",
        )
        footer = "[Space/Click] Show answer  [q] Quit session"
        if can_undo:
            footer += "  [u] Undo last"
        add_line(stdscr, max_y - 1, 0, footer, curses.color_pair(COLORS["muted"]))
        stdscr.refresh()
        _render_native_image_requests(stdscr, image_requests, config)
        key = stdscr.getch()
        if _mouse_button(key) in ("left", "right"):
            return ord(" ")
        if key in (ord(" "), 10, 13, ord("q"), ord("Q"), ord("u"), ord("U")):
            return key


def _draw_card_back(stdscr, set_name: str, card: dict, index: int, total_cards: int, config: dict, session: dict) -> int:
    voting_enabled = bool(config.get("tui", {}).get("enable_card_voting", True))
    selected_grade = 2
    while True:
        if _native_image_enabled(config):
            clear_native_images()
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()
        image_requests: list[dict] = []
        question_lines = _rich_lines(card.get("card_name", ""), config, max_x - 1)
        image_requests.extend(
            _collect_native_image_requests(
                question_lines,
                start_row=0,
                end_row_exclusive=1,
                default_width=int(config.get("tui", {}).get("image_width", 72)),
                default_height=int(config.get("tui", {}).get("image_height", 24)),
            )
        )
        _draw_styled_lines(
            stdscr,
            question_lines,
            start_row=0,
            end_row_exclusive=1,
            default_style="default",
        )
        add_line(stdscr, 0, max(0, max_x - 12), f"{index + 1}/{total_cards}")
        status, color = card_status(card)
        extra = f"{set_name} | {status} | {card.get('state', 'new')}"
        if is_leech(card, config):
            extra += " | leech"
        if voting_enabled:
            vote = get_vote(session, card)
            vote_label = "none"
            if vote > 0:
                vote_label = "upvoted"
            elif vote < 0:
                vote_label = "downvoted"
            extra += f" | vote:{vote_label}"
        add_line(stdscr, 1, 0, extra, curses.color_pair(color))
        row = 3
        answer_lines = _rich_lines(card.get("card_info", ""), config, max_x - 1)
        image_requests.extend(
            _collect_native_image_requests(
                answer_lines,
                start_row=row,
                end_row_exclusive=max_y - 4,
                default_width=int(config.get("tui", {}).get("image_width", 72)),
                default_height=int(config.get("tui", {}).get("image_height", 24)),
            )
        )
        row, _ = _draw_styled_lines(
            stdscr,
            answer_lines,
            start_row=row,
            end_row_exclusive=max_y - 4,
            default_style="default",
        )
        add_info = card.get("card_add_info", "")
        if add_info:
            row += 1
            add_line(stdscr, row, 0, "Notes:", curses.color_pair(COLORS["muted"]))
            row += 1
            notes_lines = _rich_lines(add_info, config, max_x - 1)
            image_requests.extend(
                _collect_native_image_requests(
                    notes_lines,
                    start_row=row,
                    end_row_exclusive=max_y - 4,
                    default_width=int(config.get("tui", {}).get("image_width", 72)),
                    default_height=int(config.get("tui", {}).get("image_height", 24)),
                )
            )
            row, _ = _draw_styled_lines(
                stdscr,
                notes_lines,
                start_row=row,
                end_row_exclusive=max_y - 4,
                default_style="muted",
            )
        tags = card.get("tags", [])
        if tags:
            add_line(stdscr, max_y - 3, 0, f"Tags: {', '.join(tags)}", curses.color_pair(COLORS["muted"]))
        footer = _grade_footer(selected_grade, voting_enabled)
        add_line(
            stdscr,
            max_y - 1,
            0,
            footer,
            curses.color_pair(COLORS["prompt"]),
        )
        stdscr.refresh()
        _render_native_image_requests(stdscr, image_requests, config)
        key = stdscr.getch()
        mouse_event = _mouse_event(key)
        if mouse_event == "left":
            return ord(str(selected_grade + 1))
        if mouse_event == "right":
            selected_grade = (selected_grade + 1) % len(GRADE_LABELS)
            continue
        if voting_enabled and key == ord("+"):
            set_vote(session, card, 1)
            continue
        if voting_enabled and key == ord("-"):
            set_vote(session, card, -1)
            continue
        if voting_enabled and key == ord("0"):
            set_vote(session, card, 0)
            continue
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


def _unique_cards(cards: list[dict]) -> list[dict]:
    unique = []
    seen = set()
    for card in cards:
        card_id = str(card.get("id") or id(card))
        if card_id in seen:
            continue
        seen.add(card_id)
        unique.append(card)
    return unique


def _card_label(card: dict) -> str:
    name = card.get("card_name", "Card")
    card_id = card.get("id", "?")
    return f"{name} ({card_id})"


def _select_cards_for_delete(stdscr, set_name: str, downvoted: list[dict]) -> set[str] | None:
    selected: set[int] = set()
    cursor = 0
    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()
        add_line(stdscr, 0, 0, f"Select downvoted cards to delete ({set_name})", curses.color_pair(COLORS["prompt"]))
        row = 2
        for index, card in enumerate(downvoted):
            if row >= max_y - 2:
                break
            marker = "[x]" if index in selected else "[ ]"
            prefix = ">" if index == cursor else " "
            attr = curses.A_REVERSE if index == cursor else 0
            add_line(stdscr, row, 0, f"{prefix} {marker} {_card_label(card)}"[: max_x - 1], attr)
            row += 1
        footer = "[j/k] Move  [Space] Toggle  [a] Toggle all  [Enter] Confirm  [q] Cancel"
        add_line(stdscr, max_y - 1, 0, footer, curses.color_pair(COLORS["muted"]))
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27):
            return None
        if key in (ord("j"), curses.KEY_DOWN) and cursor < len(downvoted) - 1:
            cursor += 1
            continue
        if key in (ord("k"), curses.KEY_UP) and cursor > 0:
            cursor -= 1
            continue
        if key in (ord(" "),):
            if cursor in selected:
                selected.remove(cursor)
            else:
                selected.add(cursor)
            continue
        if key in (ord("a"), ord("A")):
            if len(selected) == len(downvoted):
                selected.clear()
            else:
                selected = set(range(len(downvoted)))
            continue
        if key in (10, 13):
            return {str(downvoted[index].get("id") or id(downvoted[index])) for index in sorted(selected)}


def _remove_cards(cards: list[dict], card_ids: set[str]) -> list[dict]:
    removed = []
    kept = []
    for card in cards:
        card_id = str(card.get("id") or id(card))
        if card_id in card_ids:
            removed.append(card)
        else:
            kept.append(card)
    cards[:] = kept
    return removed


def _finalize_session(stdscr, set_name: str, cards: list[dict], session: dict, config: dict) -> None:
    downvoted = _unique_cards(downvoted_cards(session))
    if not downvoted or not bool(config.get("tui", {}).get("enable_card_voting", True)):
        show_message(stdscr, set_name, review_summary_lines(session, cards), "success")
        return
    while True:
        stdscr.erase()
        max_y, _ = stdscr.getmaxyx()
        summary = review_summary_lines(session, cards)
        add_line(stdscr, 0, 0, set_name, curses.color_pair(COLORS["success"]))
        row = 2
        for line in summary:
            add_line(stdscr, row, 0, line)
            row += 1
        row += 1
        add_line(stdscr, row, 0, "Downvoted cards:", curses.color_pair(COLORS["prompt"]))
        row += 1
        for card in downvoted:
            if row >= max_y - 3:
                break
            add_line(stdscr, row, 0, f"- {_card_label(card)}", curses.color_pair(COLORS["muted"]))
            row += 1
        footer = "[k] Keep all  [a] Delete all  [s] Select cards  [q] Finish"
        add_line(stdscr, max_y - 1, 0, footer, curses.color_pair(COLORS["muted"]))
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord("k"), ord("K"), ord("q"), ord("Q"), 27):
            show_message(stdscr, set_name, review_summary_lines(session, cards), "success")
            return
        if key in (ord("a"), ord("A")):
            removed = _remove_cards(cards, {str(card.get("id") or id(card)) for card in downvoted})
            lines = review_summary_lines(session, cards) + [f"Deleted {len(removed)} downvoted cards."]
            show_message(stdscr, set_name, lines, "success")
            return
        if key in (ord("s"), ord("S")):
            selected = _select_cards_for_delete(stdscr, set_name, downvoted)
            if selected is None:
                continue
            removed = _remove_cards(cards, selected)
            lines = review_summary_lines(session, cards) + [f"Deleted {len(removed)} selected downvoted cards."]
            show_message(stdscr, set_name, lines, "success")
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
        back_key = _draw_card_back(stdscr, set_name, card, index, len(review_cards), config, session)
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
    _finalize_session(stdscr, set_name, cards, session, config)
    return (set_name, cards)
