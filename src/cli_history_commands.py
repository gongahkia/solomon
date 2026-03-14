from __future__ import annotations

from cli_support import history_filters, history_scope_requested
from history import archive_history, export_history, prune_history, rebuild_history


def cmd_export_history(args, config: dict) -> int:
    result = export_history(args.output, format=args.format, **history_filters(args))
    print(f"Exported {result['exported']} history events to {result['destination']}")
    return 0


def cmd_archive_history(args, config: dict) -> int:
    if not history_scope_requested(args):
        raise ValueError("Refusing to archive the full history without --all or a filter.")
    filters = history_filters(args)
    result = archive_history(args.output, format=args.format, **filters)
    print(
        f"Archived {result['archived']} history events to {result['destination']} "
        f"with {result['remaining']} remaining."
    )
    return 0


def cmd_prune_history(args, config: dict) -> int:
    if not history_scope_requested(args):
        raise ValueError("Refusing to prune the full history without --all or a filter.")
    result = prune_history(**history_filters(args))
    print(f"Removed {result['removed']} history events; {result['remaining']} remain.")
    return 0


def cmd_rebuild_history(args, config: dict) -> int:
    result = rebuild_history()
    print(f"Rebuilt history with {result['events']} valid events; dropped {result['dropped_lines']} invalid lines.")
    return 0
