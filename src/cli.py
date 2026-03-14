from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

import cards as cards_app
from analytics import stats_pages
from config import load_config
from deck_ops import duplicate_card, move_card, parse_tags, reorder_card, toggle_suspend
from history import archive_history, export_history, load_history, prune_history, rebuild_history
from import_export import (
    export_to_csv,
    export_to_json,
    export_to_txt,
    import_from_csv,
    import_from_json,
    import_from_txt,
    merge_sets,
)
from schema import DOCUMENT_SETS_KEY, new_card, normalize_document, reset_card_progress, touch_card
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


def _parse_timestamp(value: str | None, label: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {label} timestamp '{value}'. Use ISO-8601.") from exc


def _history_filters(args) -> dict:
    return {
        "deck_name": _deck_name(args.deck) if getattr(args, "deck", None) else None,
        "set_name": getattr(args, "set_name", None),
        "card_id": getattr(args, "card_id", None),
        "since": _parse_timestamp(getattr(args, "since", None), "--since"),
        "before": _parse_timestamp(getattr(args, "before", None), "--before"),
    }


def _history_scope_requested(args) -> bool:
    return bool(
        getattr(args, "all", False)
        or getattr(args, "deck", None)
        or getattr(args, "set_name", None)
        or getattr(args, "card_id", None)
        or getattr(args, "since", None)
        or getattr(args, "before", None)
    )


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


def _require_set(sets: dict, set_name: str) -> list[dict]:
    if set_name not in sets:
        raise ValueError(f"Set not found: {set_name}")
    return sets[set_name]


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
                with open(path, "r", encoding="utf-8") as fhand:
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
    with open(args.source, "r", encoding="utf-8") as fhand:
        raw = json.load(fhand)
    document = normalize_document(raw, config)
    destination = args.output or args.source
    with open(destination, "w", encoding="utf-8") as fhand:
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
    _, sets = _load_managed_deck(args.deck, config)
    for set_name, cards in sets.items():
        print(f"{set_name}\t{len(cards)}")
    return 0


def cmd_list_cards(args, config: dict) -> int:
    _, sets = _load_managed_deck(args.deck, config)
    target_sets = {args.set_name: _require_set(sets, args.set_name)} if args.set_name else sets
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


def cmd_delete_deck(args, config: dict) -> int:
    deck_name = _deck_name(args.deck)
    path = sko_path(deck_name)
    if not os.path.exists(path):
        raise ValueError(f"Deck not found: {deck_name}")
    if not args.force:
        raise ValueError("Use --force to delete a deck from disk.")
    os.remove(path)
    print(f"Deleted deck {deck_name}")
    return 0


def cmd_create_set(args, config: dict) -> int:
    deck_name, sets = _load_managed_deck(args.deck, config)
    if args.set_name in sets and not args.force:
        raise ValueError(f"Set already exists: {args.set_name}")
    sets.setdefault(args.set_name, [])
    _save_managed_deck(deck_name, sets, config)
    print(f"Created set {args.set_name} in {deck_name}")
    return 0


def cmd_rename_set(args, config: dict) -> int:
    deck_name, sets = _load_managed_deck(args.deck, config)
    cards = _require_set(sets, args.set_name)
    if args.new_name in sets:
        raise ValueError(f"Set already exists: {args.new_name}")
    sets[args.new_name] = cards
    del sets[args.set_name]
    _save_managed_deck(deck_name, sets, config)
    print(f"Renamed {args.set_name} to {args.new_name}")
    return 0


def cmd_delete_set(args, config: dict) -> int:
    deck_name, sets = _load_managed_deck(args.deck, config)
    cards = _require_set(sets, args.set_name)
    if cards and not args.force:
        raise ValueError("Set is not empty; use --force to delete it.")
    del sets[args.set_name]
    _save_managed_deck(deck_name, sets, config)
    print(f"Deleted set {args.set_name} from {deck_name}")
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


def cmd_edit_card(args, config: dict) -> int:
    deck_name, sets = _load_managed_deck(args.deck, config)
    cards = _require_set(sets, args.set_name)
    _, card = _find_card(cards, args.card)
    changed = False
    if args.name is not None:
        if not args.name.strip():
            raise ValueError("Card name cannot be empty.")
        card["card_name"] = args.name
        changed = True
    if args.info is not None or args.clear_info:
        card["card_info"] = "" if args.clear_info else args.info
        changed = True
    if args.notes is not None or args.clear_notes:
        card["card_add_info"] = "" if args.clear_notes else args.notes
        changed = True
    if args.tags is not None or args.clear_tags:
        card["tags"] = [] if args.clear_tags else parse_tags(args.tags)
        changed = True
    if not changed:
        raise ValueError("No card updates were provided.")
    touch_card(card)
    _save_managed_deck(deck_name, sets, config)
    print(f"Updated {card.get('card_name')}")
    return 0


def cmd_duplicate_card(args, config: dict) -> int:
    deck_name, sets = _load_managed_deck(args.deck, config)
    cards = _require_set(sets, args.set_name)
    index, card = _find_card(cards, args.card)
    target_set = args.target_set or args.set_name
    sets.setdefault(target_set, [])
    cloned = duplicate_card(card, config)
    if target_set == args.set_name:
        cards.insert(index + 1, cloned)
    else:
        sets[target_set].append(cloned)
    _save_managed_deck(deck_name, sets, config)
    print(f"Duplicated {card.get('card_name')} into {target_set}")
    return 0


def cmd_delete_card(args, config: dict) -> int:
    deck_name, sets = _load_managed_deck(args.deck, config)
    cards = _require_set(sets, args.set_name)
    index, card = _find_card(cards, args.card)
    del cards[index]
    _save_managed_deck(deck_name, sets, config)
    print(f"Deleted {card.get('card_name')}")
    return 0


def cmd_move_card(args, config: dict) -> int:
    deck_name, sets = _load_managed_deck(args.deck, config)
    cards = _require_set(sets, args.source_set)
    sets.setdefault(args.target_set, [])
    index, card = _find_card(cards, args.card)
    move_card(sets, args.source_set, index, args.target_set)
    _save_managed_deck(deck_name, sets, config)
    print(f"Moved {card.get('card_name')} to {args.target_set}")
    return 0


def cmd_duplicate_or_move_within_set(args, config: dict) -> int:
    deck_name, sets = _load_managed_deck(args.deck, config)
    cards = _require_set(sets, args.set_name)
    index, card = _find_card(cards, args.card)
    direction = -1 if args.direction == "up" else 1
    for _ in range(max(1, args.steps)):
        next_index = reorder_card(cards, index, direction)
        if next_index == index:
            break
        index = next_index
    _save_managed_deck(deck_name, sets, config)
    print(f"Moved {card.get('card_name')} to position {index + 1} in {args.set_name}")
    return 0


def cmd_suspend_card(args, config: dict) -> int:
    deck_name, sets = _load_managed_deck(args.deck, config)
    cards = _require_set(sets, args.set_name)
    _, card = _find_card(cards, args.card)
    desired = not args.resume
    if card.get("suspended") != desired:
        toggle_suspend(card)
    _save_managed_deck(deck_name, sets, config)
    state = "resumed" if args.resume else "suspended"
    print(f"{state.capitalize()} {card.get('card_name')}")
    return 0


def cmd_reset_card(args, config: dict) -> int:
    deck_name, sets = _load_managed_deck(args.deck, config)
    cards = _require_set(sets, args.set_name)
    _, card = _find_card(cards, args.card)
    reset_card_progress(card, config)
    _save_managed_deck(deck_name, sets, config)
    print(f"Reset progress for {card.get('card_name')}")
    return 0


def cmd_review(args, config: dict) -> int:
    review_argv = [args.deck]
    if args.set_name:
        review_argv.extend(["--set", args.set_name])
    if args.due_only:
        review_argv.append("--due-only")
    if args.record_progress:
        review_argv.append("--record-progress")
    return cards_app.main(review_argv)


def cmd_export_history(args, config: dict) -> int:
    result = export_history(args.output, format=args.format, **_history_filters(args))
    print(f"Exported {result['exported']} history events to {result['destination']}")
    return 0


def cmd_archive_history(args, config: dict) -> int:
    if not _history_scope_requested(args):
        raise ValueError("Refusing to archive the full history without --all or a filter.")
    filters = _history_filters(args)
    result = archive_history(args.output, format=args.format, **filters)
    print(
        f"Archived {result['archived']} history events to {result['destination']} "
        f"with {result['remaining']} remaining."
    )
    return 0


def cmd_prune_history(args, config: dict) -> int:
    if not _history_scope_requested(args):
        raise ValueError("Refusing to prune the full history without --all or a filter.")
    result = prune_history(**_history_filters(args))
    print(f"Removed {result['removed']} history events; {result['remaining']} remain.")
    return 0


def cmd_rebuild_history(args, config: dict) -> int:
    result = rebuild_history()
    print(f"Rebuilt history with {result['events']} valid events; dropped {result['dropped_lines']} invalid lines.")
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

    subparsers.add_parser("list-decks", help="List managed Senko decks.")

    list_sets_parser = subparsers.add_parser("list-sets", help="List sets in a managed deck.")
    list_sets_parser.add_argument("deck")

    list_cards_parser = subparsers.add_parser("list-cards", help="List cards in a managed deck.")
    list_cards_parser.add_argument("deck")
    list_cards_parser.add_argument("--set", dest="set_name")

    create_deck_parser = subparsers.add_parser("create-deck", help="Create an empty managed deck.")
    create_deck_parser.add_argument("deck")
    create_deck_parser.add_argument("--force", action="store_true")

    delete_deck_parser = subparsers.add_parser("delete-deck", help="Delete a managed deck.")
    delete_deck_parser.add_argument("deck")
    delete_deck_parser.add_argument("--force", action="store_true")

    create_set_parser = subparsers.add_parser("create-set", help="Create a set inside a managed deck.")
    create_set_parser.add_argument("deck")
    create_set_parser.add_argument("set_name")
    create_set_parser.add_argument("--force", action="store_true")

    rename_set_parser = subparsers.add_parser("rename-set", help="Rename a set inside a managed deck.")
    rename_set_parser.add_argument("deck")
    rename_set_parser.add_argument("set_name")
    rename_set_parser.add_argument("new_name")

    delete_set_parser = subparsers.add_parser("delete-set", help="Delete a set from a managed deck.")
    delete_set_parser.add_argument("deck")
    delete_set_parser.add_argument("set_name")
    delete_set_parser.add_argument("--force", action="store_true")

    add_card_parser = subparsers.add_parser("add-card", help="Add a card to a managed deck.")
    add_card_parser.add_argument("deck")
    add_card_parser.add_argument("set_name")
    add_card_parser.add_argument("--name", required=True)
    add_card_parser.add_argument("--info")
    add_card_parser.add_argument("--notes")
    add_card_parser.add_argument("--tags")

    edit_card_parser = subparsers.add_parser("edit-card", help="Edit a card inside a managed deck.")
    edit_card_parser.add_argument("deck")
    edit_card_parser.add_argument("set_name")
    edit_card_parser.add_argument("card", help="Card id or exact card name.")
    edit_card_parser.add_argument("--name")
    edit_card_parser.add_argument("--info")
    edit_card_parser.add_argument("--notes")
    edit_card_parser.add_argument("--tags")
    edit_card_parser.add_argument("--clear-info", action="store_true")
    edit_card_parser.add_argument("--clear-notes", action="store_true")
    edit_card_parser.add_argument("--clear-tags", action="store_true")

    duplicate_card_parser = subparsers.add_parser("duplicate-card", help="Duplicate a card within or across sets.")
    duplicate_card_parser.add_argument("deck")
    duplicate_card_parser.add_argument("set_name")
    duplicate_card_parser.add_argument("card", help="Card id or exact card name.")
    duplicate_card_parser.add_argument("--target-set")

    delete_card_parser = subparsers.add_parser("delete-card", help="Delete a card from a managed deck.")
    delete_card_parser.add_argument("deck")
    delete_card_parser.add_argument("set_name")
    delete_card_parser.add_argument("card", help="Card id or exact card name.")

    move_card_parser = subparsers.add_parser("move-card", help="Move a card between sets.")
    move_card_parser.add_argument("deck")
    move_card_parser.add_argument("source_set")
    move_card_parser.add_argument("target_set")
    move_card_parser.add_argument("card", help="Card id or exact card name.")

    reorder_card_parser = subparsers.add_parser("reorder-card", help="Move a card up or down within a set.")
    reorder_card_parser.add_argument("deck")
    reorder_card_parser.add_argument("set_name")
    reorder_card_parser.add_argument("card", help="Card id or exact card name.")
    reorder_card_parser.add_argument("direction", choices=["up", "down"])
    reorder_card_parser.add_argument("--steps", type=int, default=1)

    suspend_parser = subparsers.add_parser("suspend-card", help="Suspend or resume a card.")
    suspend_parser.add_argument("deck")
    suspend_parser.add_argument("set_name")
    suspend_parser.add_argument("card", help="Card id or exact card name.")
    suspend_parser.add_argument("--resume", action="store_true")

    reset_parser = subparsers.add_parser("reset-card", help="Reset card progress.")
    reset_parser.add_argument("deck")
    reset_parser.add_argument("set_name")
    reset_parser.add_argument("card", help="Card id or exact card name.")

    review_parser = subparsers.add_parser("review", help="Run the lightweight terminal reviewer from the main CLI.")
    review_parser.add_argument("deck")
    review_parser.add_argument("--set", dest="set_name")
    review_parser.add_argument("--due-only", action="store_true")
    review_parser.add_argument("--record-progress", action="store_true")

    export_history_parser = subparsers.add_parser("export-history", help="Export review history to JSON or JSONL.")
    export_history_parser.add_argument("output")
    export_history_parser.add_argument("--format", choices=["json", "jsonl"], default="jsonl")
    export_history_parser.add_argument("--deck")
    export_history_parser.add_argument("--set", dest="set_name")
    export_history_parser.add_argument("--card-id")
    export_history_parser.add_argument("--since")
    export_history_parser.add_argument("--before")

    archive_history_parser = subparsers.add_parser("archive-history", help="Move matching review history events to another file.")
    archive_history_parser.add_argument("output")
    archive_history_parser.add_argument("--format", choices=["json", "jsonl"], default="jsonl")
    archive_history_parser.add_argument("--deck")
    archive_history_parser.add_argument("--set", dest="set_name")
    archive_history_parser.add_argument("--card-id")
    archive_history_parser.add_argument("--since")
    archive_history_parser.add_argument("--before")
    archive_history_parser.add_argument("--all", action="store_true")

    prune_history_parser = subparsers.add_parser("prune-history", help="Delete matching review history events in place.")
    prune_history_parser.add_argument("--deck")
    prune_history_parser.add_argument("--set", dest="set_name")
    prune_history_parser.add_argument("--card-id")
    prune_history_parser.add_argument("--since")
    prune_history_parser.add_argument("--before")
    prune_history_parser.add_argument("--all", action="store_true")

    subparsers.add_parser("rebuild-history", help="Rewrite history.jsonl while dropping malformed lines.")

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
        "delete-deck": cmd_delete_deck,
        "create-set": cmd_create_set,
        "rename-set": cmd_rename_set,
        "delete-set": cmd_delete_set,
        "add-card": cmd_add_card,
        "edit-card": cmd_edit_card,
        "duplicate-card": cmd_duplicate_card,
        "delete-card": cmd_delete_card,
        "move-card": cmd_move_card,
        "reorder-card": cmd_duplicate_or_move_within_set,
        "suspend-card": cmd_suspend_card,
        "reset-card": cmd_reset_card,
        "review": cmd_review,
        "export-history": cmd_export_history,
        "archive-history": cmd_archive_history,
        "prune-history": cmd_prune_history,
        "rebuild-history": cmd_rebuild_history,
        "stats": cmd_stats,
    }
    return commands[args.command](args, config)
