from __future__ import annotations

import json
import os

from analytics import stats_pages
from cli_support import (
    deck_name,
    load_external_data,
    load_managed_deck,
    parse_mapping,
    print_lines,
    require_set,
)
from history import load_history
from import_export import export_to_csv, export_to_json, merge_sets
from schema import DOCUMENT_SETS_KEY, normalize_document
from storage import ensure_config_dir, list_sko_files, read_sko, sko_path, write_sko


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
    field_mapping = parse_mapping(args.map or [])
    data = load_external_data(args.source, config, field_mapping=field_mapping or None)
    ensure_config_dir()
    managed_name = deck_name(args.deck)
    target_path = sko_path(managed_name)
    existing = read_sko(managed_name, config) if os.path.exists(target_path) else {}
    merged, summary = merge_sets(existing, data, args.strategy)
    write_sko(managed_name, merged, config)
    print(
        f"Imported into {managed_name}: added={summary['added']} "
        f"replaced={summary['replaced']} skipped={summary['skipped']} "
        f"replaced_sets={summary['replaced_sets']}"
    )
    return 0


def cmd_export(args, config: dict) -> int:
    managed_name, data = load_managed_deck(args.deck, config)
    output = args.output
    if not output:
        base = os.path.splitext(managed_name)[0]
        output = os.path.expanduser(f"~/Desktop/{base}.{args.format}")
    if args.format == "json":
        export_to_json(data, output, config)
    else:
        export_to_csv(data, output)
    print(f"Exported {managed_name} -> {output}")
    return 0


def cmd_list_decks(args, config: dict) -> int:
    for status in list_sko_files(config):
        state = "valid" if status["valid"] else "invalid"
        print(f"{status['filename']}\t{state}")
    return 0


def cmd_list_sets(args, config: dict) -> int:
    _, sets = load_managed_deck(args.deck, config)
    for set_name, cards in sets.items():
        print(f"{set_name}\t{len(cards)}")
    return 0


def cmd_list_cards(args, config: dict) -> int:
    _, sets = load_managed_deck(args.deck, config)
    target_sets = {args.set_name: require_set(sets, args.set_name)} if args.set_name else sets
    for set_name, cards in target_sets.items():
        for card in cards:
            status = "suspended" if card.get("suspended") else card.get("state", "new")
            print(f"{set_name}\t{card.get('id')}\t{card.get('card_name')}\t{status}")
    return 0


def cmd_stats(args, config: dict) -> int:
    if args.deck:
        managed_name = deck_name(args.deck)
        valid_statuses = [status for status in list_sko_files(config) if status["valid"] and status["filename"] == managed_name]
        history_events = load_history(deck_name=managed_name)
    else:
        valid_statuses = [status for status in list_sko_files(config) if status["valid"]]
        history_events = load_history()
    for title, lines in stats_pages(valid_statuses, history_events, config):
        print(f"[{title}]")
        print_lines(lines)
        print()
    return 0
