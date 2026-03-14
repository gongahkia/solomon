from __future__ import annotations

import argparse


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
