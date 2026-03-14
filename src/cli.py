from __future__ import annotations

import argparse
import csv
import json
import os

from config import load_config
from import_export import (
    export_to_csv,
    export_to_json,
    export_to_txt,
    import_from_csv,
    import_from_json,
    import_from_txt,
    merge_sets,
)
from schema import DOCUMENT_SETS_KEY, normalize_document, serialize_document
from storage import ensure_config_dir, inspect_sko, list_sko_files, read_sko, sko_path, write_sko


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
    deck_name = _deck_name(args.deck)
    data = read_sko(deck_name, config)
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
    import_parser.add_argument(
        "--strategy",
        choices=["skip", "replace", "keep", "replace_set"],
        default="skip",
        help="Duplicate handling strategy.",
    )
    import_parser.add_argument(
        "--map",
        action="append",
        help="Optional CSV field mapping in target=source format, e.g. set_name=Topic.",
    )

    export_parser = subparsers.add_parser("export", help="Export a managed Senko deck.")
    export_parser.add_argument("deck", help="Deck name under ~/.config/senko.")
    export_parser.add_argument("--format", choices=["json", "txt", "csv"], default="json")
    export_parser.add_argument("--output", help="Destination path.")

    return parser


def run_cli(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        return -1
    config = load_config()
    if args.command == "validate":
        return cmd_validate(args, config)
    if args.command == "migrate":
        return cmd_migrate(args, config)
    if args.command == "import":
        return cmd_import(args, config)
    if args.command == "export":
        return cmd_export(args, config)
    return 0
