from __future__ import annotations

import argparse
import os
import time
from copy import deepcopy

from config import load_config
from history import log_review_event
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
    reviewed = 0
    for set_name, cards in review_sets:
        for card in cards:
            reviewed += 1
            print(set_name)
            print(f"{reviewed}/{total_cards}")
            print(f"Q: {card.get('card_name', '')}")
            input("\nPress [Enter] to show the answer")
            clear_screen()
            print(set_name)
            print(f"{reviewed}/{total_cards}")
            print(f"Q: {card.get('card_name', '')}")
            print(f"A: {card.get('card_info', '')}")
            if card.get("card_add_info"):
                print(f"Notes: {card['card_add_info']}")
            if card.get("tags"):
                print(f"Tags: {', '.join(card['tags'])}")
            if args.record_progress:
                while True:
                    grade = input("\nGrade [1-4]: ").strip()
                    if grade in {"1", "2", "3", "4"}:
                        before = deepcopy(card)
                        sm2_review(card, int(grade) - 1, config)
                        log_review_event(
                            deck_name,
                            set_name,
                            before,
                            card,
                            int(grade) - 1,
                            "due" if args.due_only else "all",
                        )
                        break
                    print("Enter 1, 2, 3, or 4.")
            else:
                input("\nPress [Enter] to continue")
            clear_screen()
    elapsed = time.time() - start_time
    _save_if_needed(deck_name, data, config, args.record_progress)
    print(f"Reviewed {reviewed} cards in {elapsed / 60:.2f} minutes.")
    if args.record_progress and deck_name:
        print(f"Saved progress to {deck_name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
