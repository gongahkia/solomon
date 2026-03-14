from __future__ import annotations

import csv
import curses
import json
import os

from config import load_config, reset_config, save_config
from import_export import (
    export_to_csv,
    export_to_json,
    export_to_txt,
    import_from_csv,
    import_from_json,
    import_from_txt,
    infer_csv_mapping,
    merge_sets,
    preview_import,
)
from schema import is_leech
from srs import cards_due_count
from storage import ensure_config_dir, list_sko_files, read_sko, sko_path, write_sko
from tui import COLORS, select_from_list, text_input


def add_line(stdscr, y: int, x: int, text: str, attr: int = 0) -> None:
    max_x = stdscr.getmaxyx()[1]
    if y < 0 or x >= max_x:
        return
    try:
        stdscr.addstr(y, x, text[: max_x - x - 1], attr)
    except curses.error:
        pass


def wait_for_keys(stdscr, accepted: tuple[int, ...]) -> int:
    while True:
        key = stdscr.getch()
        if key in accepted:
            return key


def show_message(stdscr, title: str, lines: list[str], color_key: str = "info") -> None:
    stdscr.erase()
    add_line(stdscr, 0, 0, title, curses.color_pair(COLORS[color_key]))
    for index, line in enumerate(lines, start=2):
        add_line(stdscr, index, 0, line)
    add_line(stdscr, stdscr.getmaxyx()[0] - 1, 0, "[q] Back", curses.color_pair(COLORS["muted"]))
    stdscr.refresh()
    wait_for_keys(stdscr, (ord("q"), ord("Q"), 27, 10, 13))


def confirm_prompt(stdscr, prompt: str, color_key: str = "error") -> bool:
    stdscr.erase()
    add_line(stdscr, 0, 0, prompt, curses.color_pair(COLORS[color_key]))
    add_line(stdscr, 2, 0, "[y] Yes  [n] No", curses.color_pair(COLORS["muted"]))
    stdscr.refresh()
    return wait_for_keys(stdscr, (ord("y"), ord("Y"), ord("n"), ord("N"), 27)) in (ord("y"), ord("Y"))


def create_sko_file(name: str, config: dict) -> str:
    if not name.endswith(".sko"):
        name += ".sko"
    write_sko(name, {}, config)
    return name


def select_sko_file(stdscr, config: dict) -> str | None:
    ensure_config_dir()
    while True:
        statuses = list_sko_files(config)
        valid_statuses = [status for status in statuses if status["valid"]]
        total_cards = sum(sum(len(cards) for cards in status["sets"].values()) for status in valid_statuses)
        total_due = sum(
            sum(cards_due_count(cards) for cards in status["sets"].values()) for status in valid_statuses
        )
        items = []
        for status in statuses:
            if status["valid"]:
                n_sets = len(status["sets"])
                n_cards = sum(len(cards) for cards in status["sets"].values())
                n_due = sum(cards_due_count(cards) for cards in status["sets"].values())
                color = COLORS["error"] if n_due > 0 else COLORS["success"]
                items.append((f"{status['filename']} | {n_sets} sets | {n_cards} cards", f"{n_due} due", color))
            else:
                items.append((f"{status['filename']} | invalid deck", status["error"], COLORS["error"]))
        header = f"Senko | {len(valid_statuses)} valid files | {total_cards} cards | {total_due} due today"
        footer = "[Enter] Open  [n] New file  [d] Delete  [/] Filter  [q] Back"
        if not items:
            items = [("No files found.", "Create one with [n]", COLORS["muted"])]
        choice = select_from_list(
            stdscr,
            header,
            items,
            footer=footer,
            extra_bindings=[("n", "New file"), ("d", "Delete file")],
            searchable=True,
        )
        if choice is None:
            return None
        if isinstance(choice, tuple):
            idx, key = choice
            if key == "n":
                name = text_input(stdscr, "Filename: ", y=0, x=0)
                if name:
                    create_sko_file(name, config)
                continue
            if key == "d" and idx is not None and idx < len(statuses):
                filename = statuses[idx]["filename"]
                should_delete = True
                if config.get("tui", {}).get("confirm_delete", True):
                    should_delete = confirm_prompt(stdscr, f"Delete {filename}?")
                if should_delete:
                    os.remove(sko_path(filename))
                continue
            continue
        if not statuses:
            continue
        selected = statuses[choice]
        if not selected["valid"]:
            show_message(stdscr, selected["filename"], [selected["error"]], "error")
            continue
        return selected["filename"]


def select_flashcard_set(stdscr, sets: dict, filename: str, config: dict) -> tuple[str, list] | None:
    while True:
        set_names = list(sets.keys())
        items = []
        for set_name in set_names:
            cards = sets[set_name]
            detail_text = "Empty"
            color = COLORS["muted"]
            if cards:
                n_due = cards_due_count(cards)
                n_suspended = len([card for card in cards if card.get("suspended")])
                n_leech = len([card for card in cards if is_leech(card, config)])
                detail_text = f"{n_due} due | {n_suspended} suspended | {n_leech} leech"
                color = COLORS["error"] if n_due > 0 else COLORS["success"]
            items.append((f"{set_name} | {len(cards)} cards", detail_text, color))
        if not items:
            items = [("No sets found.", "Create one with [n]", COLORS["muted"])]
        choice = select_from_list(
            stdscr,
            "Select flashcard set",
            items,
            footer="[Enter] Open  [n] New set  [r] Rename  [d] Delete  [/] Filter  [q] Back",
            extra_bindings=[("n", "New set"), ("r", "Rename set"), ("d", "Delete set")],
            searchable=True,
        )
        if choice is None:
            return None
        if isinstance(choice, tuple):
            idx, key = choice
            if key == "n":
                name = text_input(stdscr, "Set name: ", y=0, x=0)
                if name and name not in sets:
                    sets[name] = []
                    write_sko(filename, sets, config)
                continue
            if key == "r" and idx is not None and idx < len(set_names):
                old_name = set_names[idx]
                new_name = text_input(stdscr, "New name: ", initial=old_name, y=0, x=0)
                if new_name and new_name != old_name and new_name not in sets:
                    sets[new_name] = sets.pop(old_name)
                    write_sko(filename, sets, config)
                continue
            if key == "d" and idx is not None and idx < len(set_names):
                set_name = set_names[idx]
                should_delete = True
                if config.get("tui", {}).get("confirm_delete", True):
                    should_delete = confirm_prompt(stdscr, f"Delete '{set_name}'?")
                if should_delete:
                    del sets[set_name]
                    write_sko(filename, sets, config)
                continue
            continue
        if not set_names:
            continue
        selected = set_names[choice]
        return (selected, sets[selected])


def config_editor(stdscr, config: dict) -> dict:
    field_specs = [
        ("srs", "initial_ease", "float"),
        ("srs", "minimum_ease", "float"),
        ("srs", "easy_bonus", "float"),
        ("srs", "hard_factor", "float"),
        ("srs", "learning_steps", "list"),
        ("srs", "relearning_steps", "list"),
        ("srs", "graduating_interval", "int"),
        ("srs", "easy_interval", "int"),
        ("srs", "max_interval", "int"),
        ("srs", "leech_threshold", "int"),
        ("tui", "show_stats", "bool"),
        ("tui", "confirm_delete", "bool"),
        ("tui", "show_import_preview", "bool"),
    ]
    while True:
        items = []
        for section, key, field_type in field_specs:
            value = config.get(section, {}).get(key)
            display = ",".join(str(item) for item in value) if isinstance(value, list) else str(value)
            color = COLORS["accent"] if section == "srs" else COLORS["info"]
            items.append((f"{key}: {display}", section.upper(), color))
        choice = select_from_list(
            stdscr,
            "Settings",
            items,
            footer="[Enter] Edit  [r] Reset defaults  [q] Save & back",
            extra_bindings=[("r", "Reset defaults")],
            searchable=True,
        )
        if choice is None:
            save_config(config)
            return load_config()
        if isinstance(choice, tuple):
            if choice[1] == "r":
                config = reset_config()
            continue
        section, key, field_type = field_specs[choice]
        current = config.setdefault(section, {}).get(key)
        if field_type == "bool":
            config[section][key] = not bool(current)
            continue
        initial = ",".join(str(item) for item in current) if isinstance(current, list) else str(current)
        value = text_input(stdscr, f"{key}: ", initial=initial, y=0, x=0)
        if value is None:
            continue
        if field_type == "float":
            try:
                config[section][key] = float(value)
            except ValueError:
                show_message(stdscr, "Settings", ["Invalid number."], "error")
        elif field_type == "int":
            try:
                config[section][key] = int(value)
            except ValueError:
                show_message(stdscr, "Settings", ["Invalid integer."], "error")
        elif field_type == "list":
            config[section][key] = [part.strip() for part in value.split(",") if part.strip()]


def load_csv_headers(filepath: str) -> list[str]:
    with open(filepath, "r", newline="", encoding="utf-8") as fhand:
        reader = csv.DictReader(fhand)
        return reader.fieldnames or []


def csv_mapping_screen(stdscr, filepath: str) -> dict | None:
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
        choice = select_from_list(
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
                    show_message(stdscr, "CSV mapping", [f"Map required fields first: {', '.join(missing)}"], "error")
                    continue
                return mapping
            continue
        field = fields[choice]
        options = [(header, "", COLORS["info"]) for header in headers]
        if field not in ("set_name", "card_name"):
            options.append(("(skip)", "", COLORS["muted"]))
        selected = select_from_list(
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


def import_screen(stdscr, config: dict) -> None:
    filepath = text_input(stdscr, "File path: ", y=0, x=0)
    if not filepath:
        return
    filepath = os.path.expanduser(filepath)
    if not os.path.isfile(filepath):
        show_message(stdscr, "Import", ["File not found."], "error")
        return
    try:
        csv_mapping = None
        if filepath.endswith(".txt"):
            data = import_from_txt(filepath, config)
        elif filepath.endswith(".csv"):
            csv_mapping = csv_mapping_screen(stdscr, filepath)
            if csv_mapping is None:
                return
            data = import_from_csv(filepath, config, field_mapping=csv_mapping)
        elif filepath.endswith(".json") or filepath.endswith(".sko"):
            data = import_from_json(filepath, config)
        else:
            raise ValueError("Unsupported file type. Use .txt, .csv, .json, or .sko.")
    except (ValueError, json.JSONDecodeError) as exc:
        show_message(stdscr, "Import", [str(exc)], "error")
        return
    preview = preview_import(data)
    while True:
        stdscr.erase()
        detailed_preview = config.get("tui", {}).get("show_import_preview", True)
        add_line(stdscr, 0, 0, "Import preview", curses.color_pair(COLORS["success"]))
        add_line(stdscr, 2, 0, f"Sets: {preview['set_count']} | Cards: {preview['card_count']}")
        row = 4
        if detailed_preview:
            for set_name, count in preview["sets"][:10]:
                add_line(stdscr, row, 0, f"{set_name}: {count} cards")
                row += 1
        else:
            add_line(stdscr, row, 0, "Detailed import preview is disabled in settings.")
            row += 2
        if detailed_preview and filepath.endswith(".csv") and csv_mapping:
            row += 1
            add_line(stdscr, row, 0, "CSV mapping:", curses.color_pair(COLORS["accent"]))
            row += 1
            for field, source in csv_mapping.items():
                add_line(stdscr, row, 0, f"{field} <- {source}")
                row += 1
                if row >= stdscr.getmaxyx()[0] - 3:
                    break
        add_line(
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
            name = text_input(stdscr, "Filename: ", y=0, x=0)
            if name:
                filename = create_sko_file(name, config)
                write_sko(filename, data, config)
                show_message(stdscr, "Import", [f"Saved {preview['card_count']} cards to {filename}."], "success")
            return
        if key in (ord("e"), ord("r")):
            target = select_sko_file(stdscr, config)
            if not target:
                return
            existing = read_sko(target, config)
            target_preview = preview_import(data, existing)
            if key == ord("r"):
                merged, summary = merge_sets(existing, data, "replace_set")
            else:
                stdscr.erase()
                add_line(
                    stdscr,
                    0,
                    0,
                    f"Target preview | duplicates: {target_preview['duplicate_count']}",
                    curses.color_pair(COLORS["prompt"]),
                )
                add_line(stdscr, 2, 0, "[s] Skip dupes  [p] Replace dupes  [k] Keep all", curses.color_pair(COLORS["muted"]))
                stdscr.refresh()
                strategy_key = wait_for_keys(stdscr, (ord("s"), ord("p"), ord("k"), ord("q"), ord("Q"), 27))
                if strategy_key in (ord("q"), ord("Q"), 27):
                    return
                strategy = "skip" if strategy_key == ord("s") else "replace" if strategy_key == ord("p") else "keep"
                merged, summary = merge_sets(existing, data, strategy)
            write_sko(target, merged, config)
            show_message(
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


def export_screen(stdscr, config: dict) -> None:
    filename = select_sko_file(stdscr, config)
    if not filename:
        return
    data = read_sko(filename, config)
    n_cards = sum(len(cards) for cards in data.values())
    base = os.path.splitext(filename)[0]
    stdscr.erase()
    add_line(stdscr, 0, 0, f"{filename}: {n_cards} cards", curses.color_pair(COLORS["success"]))
    add_line(stdscr, 2, 0, "[j] JSON  [t] Text  [c] CSV  [q] Cancel", curses.color_pair(COLORS["prompt"]))
    stdscr.refresh()
    while True:
        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27):
            return
        if key in (ord("j"), ord("t"), ord("c")):
            ext = ".json" if key == ord("j") else ".txt" if key == ord("t") else ".csv"
            path = text_input(
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
            elif key == ord("t"):
                export_to_txt(data, path)
            else:
                export_to_csv(data, path)
            show_message(stdscr, "Export", [f"Exported {n_cards} cards to {path}."], "success")
            return
