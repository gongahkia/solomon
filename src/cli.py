from __future__ import annotations

import argparse
import json
import os

from analytics import stats_pages
from config import load_config
from deck_ops import move_card, parse_tags, toggle_suspend
from history import load_history
from import_export import (
    export_to_csv,
    export_to_json,
    export_to_txt,
    import_from_csv,
    import_from_json,
    import_from_txt,
    merge_sets,
)
from schema import DOCUMENT_SETS_KEY, new_card, normalize_document, reset_card_progress
from storage import ensure_config_dir, list_sko_files, read_sko, sko_path, write_sko


def _deck_name(name: str) -> str:
    return name if name.endswith(".sko") else f"{name}.sko"


def _parse_mapping(entries: list[str]) -> dict:
    mapping = {}
    for entry in entries:
        if "=" not in entry:
            raise ValueError(f"Invalid mapping '{entry}'. Use target=source.")
        key, value = entry.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise ValueError(f"Invalid mapping '{entry}'. Use target=source.")
        mapping[key] = value
    return mapping


def _load_external_data(path: str, config: dict, field_mapping: dict | None = None) -> dict:
    if path.endswith(".txt"):
        return import_from_txt(path, config)
    if path.endswith(".csv"):
        return import_from_csv(path, config, field_mapping=field_mapping)
    if path.endswith(".json") or path.endswith(".sko"):
        return import_from_json(path, config)
    raise ValueError("Unsupported input file type. Use .txt, .csv, .json, or .sko.")


def _load_managed_deck(deck_name: str, config: dict) -> tuple[str, dict]:
    normalized = _deck_name(deck_name)
    return normalized, read_sko(normalized, config)


def _save_managed_deck(deck_name: str, sets: dict, config: dict) -> None:
    write_sko(_deck_name(deck_name), sets, config)


def _find_card(cards: list[dict], selector: str) -> tuple[int, dict]:
    exact_id_matches = [(index, card) for index, card in enumerate(cards) if card.get("id") == selector]
    if exact_id_matches:
        return exact_id_matches[0]
    name_matches = [
        (index, card)
        for index, card in enumerate(cards)
        if (card.get("card_name", "") or "").casefold() == selector.casefold()
    ]
    if not name_matches:
        raise ValueError(f"Card not found: {selector}")
    if len(name_matches) > 1:
        raise ValueError(f"Card selector '{selector}' is ambiguous; use a card id instead.")
    return name_matches[0]


def _print_lines(lines: list[str]) -> None:
    for line in lines:
        print(line)


def cmd_validate(args, config: dict) -> int:
    if args.paths:
        exit_code = 0
        for path in args.paths:
            try:
                with open(path, "r") as fhand:
                    raw = json.load(fhand)
                sets = normalize_document(raw, config)[DOCUMENT_SETS_KEY]
                print(f"VALID {path}: {len(sets)} sets")
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                print(f"INVALID {path}: {exc}")
                exit_code = 1
        return exit_code
    statuses = list_sko_files(config)
    exit_code = 0
    for status in statuses:
        if status["valid"]:
            print(f"VALID {status['filename']}: {len(status['sets'])} sets")
        else:
            print(f"INVALID {status['filename']}: {status['error']}")
            exit_code = 1
    return exit_code


def cmd_migrate(args, config: dict) -> int:
    with open(args.source, "r") as fhand:
        raw = json.load(fhand)
    document = normalize_document(raw, config)
    destination = args.output or args.source
    with open(destination, "w") as fhand:
        json.dump(document, fhand, indent=2)
    print(f"Migrated {args.source} -> {destination}")
    return 0


def cmd_import(args, config: dict) -> int:
    field_mapping = _parse_mapping(args.map or [])
    data = _load_external_data(args.source, config, field_mapping=field_mapping or None)
    ensure_config_dir()
    deck_name = _deck_name(args.deck)
    target_path = sko_path(deck_name)
    existing = read_sko(deck_name, config) if os.path.exists(target_path) else {}
    merged, summary = merge_sets(existing, data, args.strategy)
    write_sko(deck_name, merged, config)
    print(
        f"Imported into {deck_name}: added={summary['added']} "
        f"replaced={summary['replaced']} skipped={summary['skipped']} "
        f"replaced_sets={summary['replaced_sets']}"
    )
    return 0


def cmd_export(args, config: dict) -> int:
    deck_name, data = _load_managed_deck(args.deck, config)
    output = args.output
    if not output:
        base = os.path.splitext(deck_name)[0]
        output = os.path.expanduser(f"~/Desktop/{base}.{args.format}")
    if args.format == "json":
        export_to_json(data, output, config)
    elif args.format == "txt":
        export_to_txt(data, output)
    else:
        export_to_csv(data, output)
    print(f"Exported {deck_name} -> {output}")
    return 0


def cmd_list_decks(args, config: dict) -> int:
    for status in list_sko_files(config):
        state = "valid" if status["valid"] else "invalid"
        print(f"{status['filename']}\t{state}")
    return 0


def cmd_list_sets(args, config: dict) -> int:
    deck_name, sets = _load_managed_deck(args.deck, config)
    for set_name, cards in sets.items():
        print(f"{set_name}\t{len(cards)}")
    return 0


def cmd_list_cards(args, config: dict) -> int:
    deck_name, sets = _load_managed_deck(args.deck, config)
    target_sets = {args.set_name: sets[args.set_name]} if args.set_name else sets
    for set_name, cards in target_sets.items():
        for card in cards:
            status = "suspended" if card.get("suspended") else card.get("state", "new")
            print(f"{set_name}\t{card.get('id')}\t{card.get('card_name')}\t{status}")
    return 0


def cmd_create_deck(args, config: dict) -> int:
    ensure_config_dir()
    deck_name = _deck_name(args.deck)
    if os.path.exists(sko_path(deck_name)) and not args.force:
        raise ValueError(f"Deck already exists: {deck_name}")
    write_sko(deck_name, {}, config)
    print(f"Created deck {deck_name}")
    return 0


def cmd_create_set(args, config: dict) -> int:
    deck_name, sets = _load_managed_deck(args.deck, config)
    if args.set_name in sets and not args.force:
        raise ValueError(f"Set already exists: {args.set_name}")
    sets.setdefault(args.set_name, [])
    _save_managed_deck(deck_name, sets, config)
    print(f"Created set {args.set_name} in {deck_name}")
    return 0


def cmd_add_card(args, config: dict) -> int:
    deck_name, sets = _load_managed_deck(args.deck, config)
    sets.setdefault(args.set_name, [])
    card = new_card(
        card_name=args.name,
        card_info=args.info or "",
        card_add_info=args.notes or "",
        tags=parse_tags(args.tags or ""),
        config=config,
    )
    sets[args.set_name].append(card)
    _save_managed_deck(deck_name, sets, config)
    print(f"Added card {card['id']} to {deck_name}:{args.set_name}")
    return 0


def cmd_move_card(args, config: dict) -> int:
    deck_name, sets = _load_managed_deck(args.deck, config)
    if args.source_set not in sets:
        raise ValueError(f"Set not found: {args.source_set}")
    sets.setdefault(args.target_set, [])
    index, card = _find_card(sets[args.source_set], args.card)
    move_card(sets, args.source_set, index, args.target_set)
    _save_managed_deck(deck_name, sets, config)
    print(f"Moved {card.get('card_name')} to {args.target_set}")
    return 0


def cmd_suspend_card(args, config: dict) -> int:
    deck_name, sets = _load_managed_deck(args.deck, config)
    if args.set_name not in sets:
        raise ValueError(f"Set not found: {args.set_name}")
    _, card = _find_card(sets[args.set_name], args.card)
    desired = not args.resume
    if card.get("suspended") != desired:
        toggle_suspend(card)
    _save_managed_deck(deck_name, sets, config)
    state = "resumed" if args.resume else "suspended"
    print(f"{state.capitalize()} {card.get('card_name')}")
    return 0


def cmd_reset_card(args, config: dict) -> int:
    deck_name, sets = _load_managed_deck(args.deck, config)
    if args.set_name not in sets:
        raise ValueError(f"Set not found: {args.set_name}")
    _, card = _find_card(sets[args.set_name], args.card)
    reset_card_progress(card, config)
    _save_managed_deck(deck_name, sets, config)
    print(f"Reset progress for {card.get('card_name')}")
    return 0


def cmd_stats(args, config: dict) -> int:
    if args.deck:
        deck_name = _deck_name(args.deck)
        valid_statuses = [status for status in list_sko_files(config) if status["valid"] and status["filename"] == deck_name]
        history_events = load_history(deck_name=deck_name)
    else:
        valid_statuses = [status for status in list_sko_files(config) if status["valid"]]
        history_events = load_history()
    for title, lines in stats_pages(valid_statuses, history_events, config):
        print(f"[{title}]")
        _print_lines(lines)
        print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="senko", description="CLI flashcard tools for Senko.")
    subparsers = parser.add_subparsers(dest="command")

    validate_parser = subparsers.add_parser("validate", help="Validate one or more deck files.")
    validate_parser.add_argument("paths", nargs="*", help="Optional external JSON/.sko files to validate.")

    migrate_parser = subparsers.add_parser("migrate", help="Rewrite a legacy JSON/.sko file into the current schema.")
    migrate_parser.add_argument("source", help="Source JSON or .sko file.")
    migrate_parser.add_argument("--output", help="Destination path. Defaults to the source path.")

    import_parser = subparsers.add_parser("import", help="Import content into a managed Senko deck.")
    import_parser.add_argument("source", help="Input file path (.txt, .csv, .json, .sko).")
    import_parser.add_argument("deck", help="Target deck name under ~/.config/senko.")
    import_parser.add_argument("--strategy", choices=["skip", "replace", "keep", "replace_set"], default="skip")
    import_parser.add_argument("--map", action="append", help="Optional CSV field mapping in target=source format.")

    export_parser = subparsers.add_parser("export", help="Export a managed Senko deck.")
    export_parser.add_argument("deck", help="Deck name under ~/.config/senko.")
    export_parser.add_argument("--format", choices=["json", "txt", "csv"], default="json")
    export_parser.add_argument("--output", help="Destination path.")

    list_decks_parser = subparsers.add_parser("list-decks", help="List managed Senko decks.")

    list_sets_parser = subparsers.add_parser("list-sets", help="List sets in a managed deck.")
    list_sets_parser.add_argument("deck")

    list_cards_parser = subparsers.add_parser("list-cards", help="List cards in a managed deck.")
    list_cards_parser.add_argument("deck")
    list_cards_parser.add_argument("--set", dest="set_name")

    create_deck_parser = subparsers.add_parser("create-deck", help="Create an empty managed deck.")
    create_deck_parser.add_argument("deck")
    create_deck_parser.add_argument("--force", action="store_true")

    create_set_parser = subparsers.add_parser("create-set", help="Create a set inside a managed deck.")
    create_set_parser.add_argument("deck")
    create_set_parser.add_argument("set_name")
    create_set_parser.add_argument("--force", action="store_true")

    add_card_parser = subparsers.add_parser("add-card", help="Add a card to a managed deck.")
    add_card_parser.add_argument("deck")
    add_card_parser.add_argument("set_name")
    add_card_parser.add_argument("--name", required=True)
    add_card_parser.add_argument("--info")
    add_card_parser.add_argument("--notes")
    add_card_parser.add_argument("--tags")

    move_card_parser = subparsers.add_parser("move-card", help="Move a card between sets.")
    move_card_parser.add_argument("deck")
    move_card_parser.add_argument("source_set")
    move_card_parser.add_argument("target_set")
    move_card_parser.add_argument("card", help="Card id or exact card name.")

    suspend_parser = subparsers.add_parser("suspend-card", help="Suspend or resume a card.")
    suspend_parser.add_argument("deck")
    suspend_parser.add_argument("set_name")
    suspend_parser.add_argument("card", help="Card id or exact card name.")
    suspend_parser.add_argument("--resume", action="store_true")

    reset_parser = subparsers.add_parser("reset-card", help="Reset card progress.")
    reset_parser.add_argument("deck")
    reset_parser.add_argument("set_name")
    reset_parser.add_argument("card", help="Card id or exact card name.")

    stats_parser = subparsers.add_parser("stats", help="Print stats for all decks or a single deck.")
    stats_parser.add_argument("--deck")

    return parser


def run_cli(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        return -1
    config = load_config()
    commands = {
        "validate": cmd_validate,
        "migrate": cmd_migrate,
        "import": cmd_import,
        "export": cmd_export,
        "list-decks": cmd_list_decks,
        "list-sets": cmd_list_sets,
        "list-cards": cmd_list_cards,
        "create-deck": cmd_create_deck,
        "create-set": cmd_create_set,
        "add-card": cmd_add_card,
        "move-card": cmd_move_card,
        "suspend-card": cmd_suspend_card,
        "reset-card": cmd_reset_card,
        "stats": cmd_stats,
    }
    return commands[args.command](args, config)
