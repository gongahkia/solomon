from __future__ import annotations

import argparse
import os

from config import load_config
from rich_content import render_rich_text, styled_lines_to_ansi
from schema import touch_card
from import_export import import_from_csv, import_from_json
from review_session import (
    apply_review,
    downvoted_cards,
    get_vote,
    review_mode_from_due_only,
    reviewed_count,
    set_vote,
    session_elapsed_minutes,
    start_session,
    undo_last_review,
)
from srs import active_cards, cards_due
from storage import read_sko, write_sko


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lightweight terminal review for Senko-compatible files.")
    parser.add_argument("source", help="Managed deck name or input file path (.csv, .json, .sko).")
    parser.add_argument("--set", dest="set_name", help="Only review a single set name.")
    parser.add_argument("--due-only", action="store_true", help="Only review cards due today.")
    parser.add_argument("--record-progress", action="store_true", help="Record grades back to a managed .sko deck.")
    return parser


def _managed_deck_name(source: str) -> str | None:
    if any(source.endswith(ext) for ext in (".csv", ".json", ".sko")):
        if source.endswith(".sko") and not os.path.sep in source:
            return source
        return None
    return f"{source}.sko"


def load_cards(source: str, config: dict) -> tuple[str | None, dict]:
    managed_deck = _managed_deck_name(source)
    if managed_deck:
        return managed_deck, read_sko(managed_deck, config)
    filepath = os.path.expanduser(source)
    if filepath.endswith(".csv"):
        return None, import_from_csv(filepath, config)
    if filepath.endswith(".json") or filepath.endswith(".sko"):
        return None, import_from_json(filepath, config)
    raise ValueError("Unsupported file type. Use a managed deck name or .csv/.json/.sko file.")


def _save_if_needed(deck_name: str | None, data: dict, config: dict, record_progress: bool) -> None:
    if deck_name and record_progress:
        write_sko(deck_name, data, config)


def _maybe_handle_leech(card: dict, config: dict) -> None:
    threshold = int(config.get("srs", {}).get("leech_threshold", 8))
    if int(card.get("lapses", 0)) != threshold or card.get("suspended"):
        return
    while True:
        choice = input(f"\nLeech threshold reached ({threshold} lapses). Suspend this card? [s/k]: ").strip().lower()
        if choice == "s":
            card["suspended"] = True
            touch_card(card)
            return
        if choice in {"k", ""}:
            return
        print("Enter 's' to suspend or 'k' to keep the card active.")


def _print_rich(text: str, config: dict) -> None:
    tui_config = config.get("tui", {})
    styled = render_rich_text(
        text,
        width=100,
        image_width=int(tui_config.get("image_width", 72)),
        image_height=int(tui_config.get("image_height", 24)),
        syntax_highlighting=bool(tui_config.get("syntax_highlighting", True)),
        render_latex=bool(tui_config.get("render_latex", True)),
        show_image_warnings=bool(tui_config.get("show_image_warnings", False)),
    )
    for line in styled_lines_to_ansi(styled):
        print(line)


def _remove_cards_by_ids(data: dict, card_ids: set[str]) -> int:
    removed = 0
    for set_name in list(data.keys()):
        cards = data[set_name]
        kept = []
        for card in cards:
            card_id = str(card.get("id") or id(card))
            if card_id in card_ids:
                removed += 1
                continue
            kept.append(card)
        data[set_name] = kept
    return removed


def _handle_downvoted_removal(deck_name: str | None, data: dict, session: dict, config: dict, record_progress: bool) -> int:
    downvoted = []
    seen = set()
    for card in downvoted_cards(session):
        card_id = str(card.get("id") or id(card))
        if card_id in seen:
            continue
        seen.add(card_id)
        downvoted.append(card)
    if not downvoted:
        return 0
    print("\nDownvoted cards:")
    for index, card in enumerate(downvoted, start=1):
        print(f"{index}. {card.get('card_name', 'Card')} ({card.get('id', '?')})")
    if not deck_name or not record_progress:
        print("Downvoted cards were surfaced only. Use a managed deck with --record-progress to delete now.")
        return 0
    while True:
        action = input("\nDelete downvoted cards? [a] all  [s] select  [k] keep: ").strip().lower()
        if action in {"k", ""}:
            return 0
        if action == "a":
            return _remove_cards_by_ids(data, {str(card.get("id") or id(card)) for card in downvoted})
        if action == "s":
            raw = input("Enter card numbers to delete (comma-separated): ").strip()
            if not raw:
                return 0
            selected_ids = set()
            for token in raw.split(","):
                token = token.strip()
                if not token.isdigit():
                    continue
                index = int(token) - 1
                if 0 <= index < len(downvoted):
                    selected_ids.add(str(downvoted[index].get("id") or id(downvoted[index])))
            return _remove_cards_by_ids(data, selected_ids)
        print("Enter 'a', 's', or 'k'.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config()
    try:
        deck_name, data = load_cards(args.source, config)
    except Exception as exc:
        print(f"Error: {exc}")
        return 1
    if args.record_progress and not deck_name:
        print("Error: --record-progress is only supported for managed .sko decks.")
        return 1
    if args.set_name:
        if args.set_name not in data:
            print(f"Set not found: {args.set_name}")
            return 1
        data = {args.set_name: data[args.set_name]}
    review_sets = []
    for set_name, cards in data.items():
        review_cards = cards_due(cards) if args.due_only else active_cards(cards)
        if review_cards:
            review_sets.append((set_name, review_cards))
    total_cards = sum(len(cards) for _, cards in review_sets)
    if not total_cards:
        print("No cards available for review.")
        return 0
    clear_screen()
    should_stop = False
    set_offset = 0
    review_mode = review_mode_from_due_only(args.due_only)
    session = start_session([], review_mode)
    for set_name, cards in review_sets:
        index = 0
        while index < len(cards):
            card = cards[index]
            position = set_offset + index + 1
            print(set_name)
            print(f"{position}/{total_cards}")
            print("Q:")
            _print_rich(card.get("card_name", ""), config)
            input("\nPress [Enter] to show the answer")
            clear_screen()
            print(set_name)
            print(f"{position}/{total_cards}")
            print("Q:")
            _print_rich(card.get("card_name", ""), config)
            print("A:")
            _print_rich(card.get("card_info", ""), config)
            if card.get("card_add_info"):
                print("Notes:")
                _print_rich(card["card_add_info"], config)
            if card.get("tags"):
                print(f"Tags: {', '.join(card['tags'])}")
            if args.record_progress:
                while True:
                    voting_enabled = bool(config.get("tui", {}).get("enable_card_voting", True))
                    if voting_enabled:
                        vote = get_vote(session, card)
                        vote_label = "none"
                        if vote > 0:
                            vote_label = "upvoted"
                        elif vote < 0:
                            vote_label = "downvoted"
                        print(f"Vote: {vote_label}  (+ upvote, - downvote, 0 clear)")
                    prompt = "\nGrade [1-4]"
                    if session["history"]:
                        prompt += " | [u] Undo last"
                    prompt += " | [q] Quit: "
                    grade = input(prompt).strip().lower()
                    if voting_enabled and grade in {"+", "-", "0"}:
                        set_vote(session, card, {"+": 1, "-": -1, "0": 0}[grade])
                        continue
                    if grade == "u" and session["history"]:
                        undo_last_review(session, deck_name=deck_name, set_name=set_name)
                        index = max(0, index - 1)
                        clear_screen()
                        break
                    if grade == "q":
                        should_stop = True
                        break
                    if grade in {"1", "2", "3", "4"}:
                        grade_value = int(grade) - 1
                        apply_review(
                            session,
                            deck_name=deck_name,
                            set_name=set_name,
                            card=card,
                            grade=grade_value,
                            config=config,
                            leech_handler=_maybe_handle_leech,
                        )
                        index += 1
                        break
                    print("Enter 1, 2, 3, 4, 'u', or 'q'.")
                if should_stop:
                    clear_screen()
                    break
                if session["history"] and session["history"][-1]["card"] is not card:
                    continue
            else:
                input("\nPress [Enter] to continue")
                index += 1
            clear_screen()
            if should_stop:
                break
        set_offset += len(cards)
    removed_cards = _handle_downvoted_removal(deck_name, data, session, config, args.record_progress)
    _save_if_needed(deck_name, data, config, args.record_progress)
    reviewed = reviewed_count(session) if args.record_progress else total_cards
    print(f"Reviewed {reviewed} cards in {session_elapsed_minutes(session):.2f} minutes.")
    if args.record_progress:
        print(
            "Again {again} | Hard {hard} | Good {good} | Easy {easy}".format(
                again=session["counts"][0],
                hard=session["counts"][1],
                good=session["counts"][2],
                easy=session["counts"][3],
            )
        )
        print(f"Downvoted {len(downvoted_cards(session))} cards.")
    if removed_cards:
        print(f"Deleted {removed_cards} downvoted cards.")
        if deck_name:
            write_sko(deck_name, data, config)
    if args.record_progress and deck_name:
        print(f"Saved progress to {deck_name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
