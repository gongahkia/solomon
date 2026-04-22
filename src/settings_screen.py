from __future__ import annotations

from collections.abc import Callable

from config import load_config, reset_config, save_config
from screen_common import show_message
from tui import COLORS, select_from_list, text_input


def config_editor(
    stdscr,
    config: dict,
    *,
    select_list: Callable = select_from_list,
    text_reader: Callable = text_input,
    show: Callable = show_message,
) -> dict:
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
        ("tui", "syntax_highlighting", "bool"),
        ("tui", "render_latex", "bool"),
        ("tui", "show_image_warnings", "bool"),
        ("tui", "native_image_rendering", "bool"),
        ("tui", "image_width", "int"),
        ("tui", "image_height", "int"),
        ("tui", "enable_card_voting", "bool"),
    ]
    while True:
        items = []
        for section, key, field_type in field_specs:
            value = config.get(section, {}).get(key)
            display = ",".join(str(item) for item in value) if isinstance(value, list) else str(value)
            color = COLORS["accent"] if section == "srs" else COLORS["info"]
            items.append((f"{key}: {display}", section.upper(), color))
        choice = select_list(
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
        value = text_reader(stdscr, f"{key}: ", initial=initial, y=0, x=0)
        if value is None:
            continue
        if field_type == "float":
            try:
                config[section][key] = float(value)
            except ValueError:
                show(stdscr, "Settings", ["Invalid number."], "error")
        elif field_type == "int":
            try:
                config[section][key] = int(value)
            except ValueError:
                show(stdscr, "Settings", ["Invalid integer."], "error")
        elif field_type == "list":
            config[section][key] = [part.strip() for part in value.split(",") if part.strip()]
