# mypy: ignore-errors

from __future__ import annotations

import sys

from cli import run_cli
from config import load_config
from deck_browser import select_flashcard_set, select_sko_file
from deck_ops import card_detail, duplicate_card, move_card, parse_tags, reorder_card, toggle_suspend
from history_view import show_history_screen
from review_flow import render_review_session
from screen_common import confirm_prompt, show_message
from schema import new_card, reset_card_progress, touch_card
from settings_screen import config_editor
from stats_view import show_stats_screen
from storage import ensure_config_dir, list_sko_files, read_sko, write_sko
from transfer_screens import export_screen, import_screen
from tui import COLORS, multiline_input, run_app, select_from_list, text_input


def edit_card_fields(stdscr, title: str, initial: dict | None) -> dict | None:
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
    result = edit_card_fields(stdscr, "Edit card", card)
    if result is None:
        return None
    card["card_name"] = result["card_name"]
    card["card_info"] = result["card_info"]
    card["card_add_info"] = result["card_add_info"]
    card["tags"] = result["tags"]
    touch_card(card)
    return card


def add_sko_card(stdscr, config: dict) -> dict | None:
    result = edit_card_fields(stdscr, "Add new card", None)
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
                move_card(sets, set_name, choice, target)
                if not cards:
                    show_message(stdscr, set_name, ["Set is now empty after moving the card."], "muted")
        elif action == 3:
            if reorder_card(cards, choice, -1) == choice:
                show_message(stdscr, set_name, ["Card is already at the top."], "muted")
        elif action == 4:
            if reorder_card(cards, choice, 1) == choice:
                show_message(stdscr, set_name, ["Card is already at the bottom."], "muted")
        elif action == 5:
            toggle_suspend(card)
        elif action == 6:
            reset_card_progress(card, config)
        elif action == 7:
            should_delete = True
            if config.get("tui", {}).get("confirm_delete", True):
                should_delete = confirm_prompt(stdscr, f"Delete '{card.get('card_name', '?')}'?")
            if should_delete:
                del cards[choice]


def deck_screen(stdscr, filename: str, config: dict, direct_review: bool = False) -> None:
    sets = read_sko(filename, config)
    while True:
        selection = select_flashcard_set(stdscr, sets, filename, config)
        if selection is None:
            return
        set_name, cards = selection
        if direct_review:
            _, cards = render_review_session(stdscr, filename, set_name, cards, config)
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
            _, cards = render_review_session(stdscr, filename, set_name, cards, config)
            sets[set_name] = cards
        else:
            set_name, sets = manage_cards_loop(stdscr, sets, set_name, config)
        write_sko(filename, sets, config)


def menu_sko(stdscr) -> None:
    ensure_config_dir()
    config = load_config()
    while True:
        menu_items = [
            ("review", ("Review cards", "", COLORS["accent"])),
            ("browse", ("Browse decks", "", COLORS["info"])),
            ("import", ("Import cards", "", COLORS["success"])),
            ("export", ("Export cards", "", COLORS["success"])),
            ("history", ("History", "", COLORS["accent"])),
        ]
        if config.get("tui", {}).get("show_stats", True):
            menu_items.append(("stats", ("Statistics", "", COLORS["muted"])))
        menu_items.extend(
            [
                ("settings", ("Settings", "", COLORS["prompt"])),
                ("quit", ("Quit", "", COLORS["error"])),
            ]
        )
        choice = select_from_list(
            stdscr,
            "Senko flashcards",
            [item for _, item in menu_items],
            footer="Spot issues? Ping me on Github @gongahkia.",
        )
        if choice is None:
            return
        if isinstance(choice, tuple):
            continue
        selected_action = menu_items[choice][0]
        if selected_action == "quit":
            return
        if selected_action == "review":
            filename = select_sko_file(stdscr, config)
            if filename:
                deck_screen(stdscr, filename, config, direct_review=True)
        elif selected_action == "browse":
            filename = select_sko_file(stdscr, config)
            if filename:
                deck_screen(stdscr, filename, config)
        elif selected_action == "import":
            import_screen(stdscr, config)
        elif selected_action == "export":
            export_screen(stdscr, config)
        elif selected_action == "history":
            show_history_screen(stdscr, config)
        elif selected_action == "stats":
            show_stats_screen(stdscr, [status for status in list_sko_files(config) if status["valid"]], config)
        elif selected_action == "settings":
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
