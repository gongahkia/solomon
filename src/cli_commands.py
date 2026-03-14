from __future__ import annotations

from cli_content_commands import (
    cmd_export,
    cmd_import,
    cmd_list_cards,
    cmd_list_decks,
    cmd_list_sets,
    cmd_migrate,
    cmd_stats,
    cmd_validate,
)
from cli_history_commands import (
    cmd_archive_history,
    cmd_export_history,
    cmd_prune_history,
    cmd_rebuild_history,
)
from cli_manage_commands import (
    cmd_add_card,
    cmd_create_deck,
    cmd_create_set,
    cmd_delete_card,
    cmd_delete_deck,
    cmd_delete_set,
    cmd_duplicate_card,
    cmd_edit_card,
    cmd_move_card,
    cmd_rename_set,
    cmd_reorder_card,
    cmd_reset_card,
    cmd_review,
    cmd_suspend_card,
)


COMMANDS = {
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
    "reorder-card": cmd_reorder_card,
    "suspend-card": cmd_suspend_card,
    "reset-card": cmd_reset_card,
    "review": cmd_review,
    "export-history": cmd_export_history,
    "archive-history": cmd_archive_history,
    "prune-history": cmd_prune_history,
    "rebuild-history": cmd_rebuild_history,
    "stats": cmd_stats,
}
