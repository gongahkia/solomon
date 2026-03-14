from __future__ import annotations

import argparse
import os
import sys
import time

from config import load_config
from import_export import import_from_csv, import_from_json, import_from_txt
from srs import active_cards, cards_due


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def load_cards(filepath: str, config: dict) -> dict:
    if filepath.endswith(".txt"):
        return import_from_txt(filepath, config)
    if filepath.endswith(".csv"):
        return import_from_csv(filepath, config)
    if filepath.endswith(".json") or filepath.endswith(".sko"):
        return import_from_json(filepath, config)
    raise ValueError("Unsupported file type. Use .txt, .csv, .json, or .sko.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lightweight terminal review for Senko-compatible files.")
    parser.add_argument("filepath", help="Input file path (.txt, .csv, .json, .sko).")
    parser.add_argument("--set", dest="set_name", help="Only review a single set name.")
    parser.add_argument("--due-only", action="store_true", help="Only review cards due today.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    filepath = os.path.expanduser(args.filepath)
    config = load_config()
    try:
        data = load_cards(filepath, config)
    except Exception as exc:
        print(f"Error: {exc}")
        return 1
    if args.set_name:
        if args.set_name not in data:
            print(f"Set not found: {args.set_name}")
            return 1
        data = {args.set_name: data[args.set_name]}
    review_sets = []
    for set_name, cards in data.items():
        review_cards = cards_due(cards) if args.due_only else active_cards(cards, include_suspended=True)
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
            input("\nPress [Enter] to continue")
            clear_screen()
    elapsed = time.time() - start_time
    print(f"Reviewed {reviewed} cards in {elapsed / 60:.2f} minutes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
