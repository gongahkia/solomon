from __future__ import annotations

from deck_browser import (
    create_sko_file as _create_sko_file,
    select_flashcard_set as _select_flashcard_set,
    select_sko_file as _select_sko_file,
)
from screen_common import add_line, confirm_prompt, show_message, wait_for_keys
from settings_screen import config_editor as _config_editor
from transfer_screens import (
    csv_mapping_screen as _csv_mapping_screen,
    export_screen as _export_screen,
    import_screen as _import_screen,
    load_csv_headers,
)
from tui import select_from_list, text_input


def create_sko_file(name: str, config: dict) -> str:
    return _create_sko_file(name, config)


def select_sko_file(stdscr, config: dict) -> str | None:
    return _select_sko_file(
        stdscr,
        config,
        select_list=select_from_list,
        text_reader=text_input,
        confirm=confirm_prompt,
        show=show_message,
    )


def select_flashcard_set(stdscr, sets: dict, filename: str, config: dict) -> tuple[str, list] | None:
    return _select_flashcard_set(
        stdscr,
        sets,
        filename,
        config,
        select_list=select_from_list,
        text_reader=text_input,
        confirm=confirm_prompt,
    )


def config_editor(stdscr, config: dict) -> dict:
    return _config_editor(
        stdscr,
        config,
        select_list=select_from_list,
        text_reader=text_input,
        show=show_message,
    )


def csv_mapping_screen(stdscr, filepath: str) -> dict | None:
    return _csv_mapping_screen(
        stdscr,
        filepath,
        select_list=select_from_list,
        show=show_message,
    )


def import_screen(stdscr, config: dict) -> None:
    return _import_screen(
        stdscr,
        config,
        text_reader=text_input,
        mapping_screen=csv_mapping_screen,
        create_file=create_sko_file,
        select_file=select_sko_file,
        show=show_message,
        add=add_line,
        wait=wait_for_keys,
    )


def export_screen(stdscr, config: dict) -> None:
    return _export_screen(
        stdscr,
        config,
        select_file=select_sko_file,
        text_reader=text_input,
        show=show_message,
        add=add_line,
    )
