from __future__ import annotations

import csv
import curses
import json
import os
from collections.abc import Callable

from deck_browser import create_sko_file, select_sko_file
from import_export import (
    export_to_csv,
    export_to_json,
    import_from_csv,
    import_from_json,
    infer_csv_mapping,
    merge_sets,
    preview_import,
)
from screen_common import add_line, show_message, wait_for_keys
from storage import read_sko, write_sko
from tui import COLORS, select_from_list, text_input


def load_csv_headers(filepath: str) -> list[str]:
    with open(filepath, "r", newline="", encoding="utf-8") as fhand:
        reader = csv.DictReader(fhand)
        return reader.fieldnames or []


def csv_mapping_screen(
    stdscr,
    filepath: str,
    *,
    select_list: Callable = select_from_list,
    show: Callable = show_message,
) -> dict | None:
    headers = load_csv_headers(filepath)
    if not headers:
        raise ValueError("CSV file has no header row.")
    fields = [
        "set_name",
        "card_name",
        "card_info",
        "card_add_info",
        "card_date",
        "tags",
        "suspended",
        "ease_factor",
        "interval",
        "repetitions",
    ]
    mapping, _ = infer_csv_mapping(headers)
    while True:
        missing = [field for field in ("set_name", "card_name") if field not in mapping]
        items = []
        for field in fields:
            current = mapping.get(field, "(unmapped)")
            color = COLORS["error"] if field in missing else COLORS["info"]
            items.append((field, current, color))
        choice = select_list(
            stdscr,
            f"CSV field mapping | missing: {', '.join(missing) or 'none'}",
            items,
            footer="[Enter] Edit field  [i] Import  [a] Auto-map  [q] Cancel",
            extra_bindings=[("i", "Import"), ("a", "Auto-map")],
        )
        if choice is None:
            return None
        if isinstance(choice, tuple):
            if choice[1] == "a":
                mapping, _ = infer_csv_mapping(headers)
                continue
            if choice[1] == "i":
                if missing:
                    show(stdscr, "CSV mapping", [f"Map required fields first: {', '.join(missing)}"], "error")
                    continue
                return mapping
            continue
        field = fields[choice]
        options = [(header, "", COLORS["info"]) for header in headers]
        if field not in ("set_name", "card_name"):
            options.append(("(skip)", "", COLORS["muted"]))
        selected = select_list(
            stdscr,
            f"Map {field}",
            options,
            footer="[Enter] Select  [q] Back",
            searchable=True,
        )
        if selected is None:
            continue
        if selected == len(headers) and field not in ("set_name", "card_name"):
            mapping.pop(field, None)
        else:
            mapping[field] = headers[selected]


def import_screen(
    stdscr,
    config: dict,
    *,
    text_reader: Callable = text_input,
    mapping_screen: Callable = csv_mapping_screen,
    create_file: Callable = create_sko_file,
    select_file: Callable = select_sko_file,
    show: Callable = show_message,
    add: Callable = add_line,
    wait: Callable = wait_for_keys,
) -> None:
    filepath = text_reader(stdscr, "File path: ", y=0, x=0)
    if not filepath:
        return
    filepath = os.path.expanduser(filepath)
    if not os.path.isfile(filepath):
        show(stdscr, "Import", ["File not found."], "error")
        return
    try:
        csv_mapping = None
        if filepath.endswith(".csv"):
            csv_mapping = mapping_screen(stdscr, filepath)
            if csv_mapping is None:
                return
            data = import_from_csv(filepath, config, field_mapping=csv_mapping)
        elif filepath.endswith(".json") or filepath.endswith(".sko"):
            data = import_from_json(filepath, config)
        else:
            raise ValueError("Unsupported file type. Use .csv, .json, or .sko.")
    except (ValueError, json.JSONDecodeError) as exc:
        show(stdscr, "Import", [str(exc)], "error")
        return
    preview = preview_import(data)
    while True:
        stdscr.erase()
        detailed_preview = config.get("tui", {}).get("show_import_preview", True)
        add(stdscr, 0, 0, "Import preview", curses.color_pair(COLORS["success"]))
        add(stdscr, 2, 0, f"Sets: {preview['set_count']} | Cards: {preview['card_count']}")
        row = 4
        if detailed_preview:
            for set_name, count in preview["sets"][:10]:
                add(stdscr, row, 0, f"{set_name}: {count} cards")
                row += 1
        else:
            add(stdscr, row, 0, "Detailed import preview is disabled in settings.")
            row += 2
        if detailed_preview and filepath.endswith(".csv") and csv_mapping:
            row += 1
            add(stdscr, row, 0, "CSV mapping:", curses.color_pair(COLORS["accent"]))
            row += 1
            for field, source in csv_mapping.items():
                add(stdscr, row, 0, f"{field} <- {source}")
                row += 1
                if row >= stdscr.getmaxyx()[0] - 3:
                    break
        add(
            stdscr,
            stdscr.getmaxyx()[0] - 1,
            0,
            "[n] New deck  [e] Merge  [r] Replace sets  [q] Cancel",
            curses.color_pair(COLORS["muted"]),
        )
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27):
            return
        if key == ord("n"):
            name = text_reader(stdscr, "Filename: ", y=0, x=0)
            if name:
                filename = create_file(name, config)
                write_sko(filename, data, config)
                show(stdscr, "Import", [f"Saved {preview['card_count']} cards to {filename}."], "success")
            return
        if key in (ord("e"), ord("r")):
            target = select_file(stdscr, config)
            if not target:
                return
            existing = read_sko(target, config)
            target_preview = preview_import(data, existing)
            if key == ord("r"):
                merged, summary = merge_sets(existing, data, "replace_set")
            else:
                stdscr.erase()
                add(
                    stdscr,
                    0,
                    0,
                    f"Target preview | duplicates: {target_preview['duplicate_count']}",
                    curses.color_pair(COLORS["prompt"]),
                )
                add(stdscr, 2, 0, "[s] Skip dupes  [p] Replace dupes  [k] Keep all", curses.color_pair(COLORS["muted"]))
                stdscr.refresh()
                strategy_key = wait(stdscr, (ord("s"), ord("p"), ord("k"), ord("q"), ord("Q"), 27))
                if strategy_key in (ord("q"), ord("Q"), 27):
                    return
                strategy = "skip" if strategy_key == ord("s") else "replace" if strategy_key == ord("p") else "keep"
                merged, summary = merge_sets(existing, data, strategy)
            write_sko(target, merged, config)
            show(
                stdscr,
                "Import",
                [
                    f"Updated {target}.",
                    f"Added: {summary['added']}",
                    f"Replaced duplicates: {summary['replaced']}",
                    f"Skipped duplicates: {summary['skipped']}",
                    f"Replaced sets: {summary['replaced_sets']}",
                ],
                "success",
            )
            return


def export_screen(
    stdscr,
    config: dict,
    *,
    select_file: Callable = select_sko_file,
    text_reader: Callable = text_input,
    show: Callable = show_message,
    add: Callable = add_line,
) -> None:
    filename = select_file(stdscr, config)
    if not filename:
        return
    data = read_sko(filename, config)
    n_cards = sum(len(cards) for cards in data.values())
    base = os.path.splitext(filename)[0]
    stdscr.erase()
    add(stdscr, 0, 0, f"{filename}: {n_cards} cards", curses.color_pair(COLORS["success"]))
    add(stdscr, 2, 0, "[j] JSON  [c] CSV  [q] Cancel", curses.color_pair(COLORS["prompt"]))
    stdscr.refresh()
    while True:
        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27):
            return
        if key in (ord("j"), ord("c")):
            ext = ".json" if key == ord("j") else ".csv"
            path = text_reader(
                stdscr,
                "Output path: ",
                initial=os.path.expanduser(f"~/Desktop/{base}{ext}"),
                y=0,
                x=0,
            )
            if not path:
                return
            path = os.path.expanduser(path)
            if key == ord("j"):
                export_to_json(data, path, config)
            else:
                export_to_csv(data, path)
            show(stdscr, "Export", [f"Exported {n_cards} cards to {path}."], "success")
            return
