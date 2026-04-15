from __future__ import annotations

import argparse
import os

from config import load_config
from schema import touch_card
from import_export import import_from_csv, import_from_json
from review_session import (
    apply_review,
    review_mode_from_due_only,
    reviewed_count,
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
            print(f"Q: {card.get('card_name', '')}")
            input("\nPress [Enter] to show the answer")
            clear_screen()
            print(set_name)
            print(f"{position}/{total_cards}")
            print(f"Q: {card.get('card_name', '')}")
            print(f"A: {card.get('card_info', '')}")
            if card.get("card_add_info"):
                print(f"Notes: {card['card_add_info']}")
            if card.get("tags"):
                print(f"Tags: {', '.join(card['tags'])}")
            if args.record_progress:
                while True:
                    prompt = "\nGrade [1-4]"
                    if session["history"]:
                        prompt += " | [u] Undo last"
                    prompt += " | [q] Quit: "
                    grade = input(prompt).strip().lower()
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
    if args.record_progress and deck_name:
        print(f"Saved progress to {deck_name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
