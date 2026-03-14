from __future__ import annotations

import argparse
import os
import time
from copy import deepcopy

from config import load_config
from deck_ops import restore_card
from history import log_review_event
from schema import touch_card
from import_export import import_from_csv, import_from_json, import_from_txt
from srs import active_cards, cards_due, sm2_review
from storage import read_sko, write_sko


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lightweight terminal review for Senko-compatible files.")
    parser.add_argument("source", help="Managed deck name or input file path (.txt, .csv, .json, .sko).")
    parser.add_argument("--set", dest="set_name", help="Only review a single set name.")
    parser.add_argument("--due-only", action="store_true", help="Only review cards due today.")
    parser.add_argument("--record-progress", action="store_true", help="Record grades back to a managed .sko deck.")
    return parser


def _managed_deck_name(source: str) -> str | None:
    if any(source.endswith(ext) for ext in (".txt", ".csv", ".json", ".sko")):
        if source.endswith(".sko") and not os.path.sep in source:
            return source
        return None
    return f"{source}.sko"


def load_cards(source: str, config: dict) -> tuple[str | None, dict]:
    managed_deck = _managed_deck_name(source)
    if managed_deck:
        return managed_deck, read_sko(managed_deck, config)
    filepath = os.path.expanduser(source)
    if filepath.endswith(".txt"):
        return None, import_from_txt(filepath, config)
    if filepath.endswith(".csv"):
        return None, import_from_csv(filepath, config)
    if filepath.endswith(".json") or filepath.endswith(".sko"):
        return None, import_from_json(filepath, config)
    raise ValueError("Unsupported file type. Use a managed deck name or .txt/.csv/.json/.sko file.")


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
    start_time = time.time()
    session_counts = {0: 0, 1: 0, 2: 0, 3: 0}
    should_stop = False
    set_offset = 0
    for set_name, cards in review_sets:
        review_history = []
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
                    if review_history:
                        prompt += " | [u] Undo last"
                    prompt += " | [q] Quit: "
                    grade = input(prompt).strip().lower()
                    if grade == "u" and review_history:
                        last = review_history.pop()
                        restore_card(last["card"], last["snapshot"])
                        session_counts[last["grade"]] -= 1
                        index = max(0, index - 1)
                        clear_screen()
                        break
                    if grade == "q":
                        should_stop = True
                        break
                    if grade in {"1", "2", "3", "4"}:
                        before = deepcopy(card)
                        grade_value = int(grade) - 1
                        sm2_review(card, grade_value, config)
                        _maybe_handle_leech(card, config)
                        log_review_event(
                            deck_name,
                            set_name,
                            before,
                            card,
                            grade_value,
                            "due" if args.due_only else "all",
                        )
                        session_counts[grade_value] += 1
                        review_history.append({"card": card, "snapshot": before, "grade": grade_value})
                        index += 1
                        break
                    print("Enter 1, 2, 3, 4, 'u', or 'q'.")
                if should_stop:
                    clear_screen()
                    break
                if review_history and review_history[-1]["card"] is not card:
                    continue
            else:
                input("\nPress [Enter] to continue")
                index += 1
            clear_screen()
        if should_stop:
            break
        set_offset += len(cards)
    elapsed = time.time() - start_time
    _save_if_needed(deck_name, data, config, args.record_progress)
    reviewed = sum(session_counts.values()) if args.record_progress else total_cards
    print(f"Reviewed {reviewed} cards in {elapsed / 60:.2f} minutes.")
    if args.record_progress:
        print(
            "Again {again} | Hard {hard} | Good {good} | Easy {easy}".format(
                again=session_counts[0],
                hard=session_counts[1],
                good=session_counts[2],
                easy=session_counts[3],
            )
        )
    if args.record_progress and deck_name:
        print(f"Saved progress to {deck_name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
