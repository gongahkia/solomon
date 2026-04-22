from __future__ import annotations

import copy
import json
import os

CONFIG_PATH = os.path.expanduser("~/.config/senko/config.json")
DEFAULT_CONFIG = {
    "srs": {
        "initial_ease": 2.5,
        "minimum_ease": 1.3,
        "easy_bonus": 1.3,
        "hard_factor": 0.8,
        "learning_steps": [1, 3],
        "relearning_steps": [1, 3],
        "graduating_interval": 6,
        "easy_interval": 8,
        "max_interval": 365,
        "leech_threshold": 8,
    },
    "tui": {
        "show_stats": True,
        "confirm_delete": True,
        "show_import_preview": True,
        "syntax_highlighting": True,
        "render_latex": True,
        "image_width": 72,
        "image_height": 24,
        "enable_card_voting": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _coerce_float(value, default: float, minimum: float | None = None) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed


def _coerce_int(value, default: int, minimum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed


def _coerce_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _coerce_int_list(value, default: list[int]) -> list[int]:
    if not isinstance(value, list):
        return copy.deepcopy(default)
    result = []
    for item in value:
        try:
            parsed = int(item)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            result.append(parsed)
    return result or copy.deepcopy(default)


def normalize_config(config: dict | None) -> dict:
    merged = _deep_merge(DEFAULT_CONFIG, config if isinstance(config, dict) else {})
    srs = merged["srs"]
    tui = merged["tui"]
    normalized = copy.deepcopy(DEFAULT_CONFIG)
    normalized["srs"]["initial_ease"] = _coerce_float(srs.get("initial_ease"), 2.5, 1.3)
    normalized["srs"]["minimum_ease"] = _coerce_float(srs.get("minimum_ease"), 1.3, 1.0)
    normalized["srs"]["easy_bonus"] = _coerce_float(srs.get("easy_bonus"), 1.3, 1.0)
    normalized["srs"]["hard_factor"] = _coerce_float(srs.get("hard_factor"), 0.8, 0.1)
    normalized["srs"]["learning_steps"] = _coerce_int_list(srs.get("learning_steps"), [1, 3])
    normalized["srs"]["relearning_steps"] = _coerce_int_list(srs.get("relearning_steps"), [1, 3])
    normalized["srs"]["graduating_interval"] = _coerce_int(srs.get("graduating_interval"), 6, 1)
    normalized["srs"]["easy_interval"] = _coerce_int(
        srs.get("easy_interval"),
        max(normalized["srs"]["graduating_interval"], 8),
        1,
    )
    normalized["srs"]["max_interval"] = _coerce_int(srs.get("max_interval"), 365, 1)
    normalized["srs"]["leech_threshold"] = _coerce_int(srs.get("leech_threshold"), 8, 1)
    normalized["tui"]["show_stats"] = _coerce_bool(tui.get("show_stats"), True)
    normalized["tui"]["confirm_delete"] = _coerce_bool(tui.get("confirm_delete"), True)
    normalized["tui"]["show_import_preview"] = _coerce_bool(tui.get("show_import_preview"), True)
    normalized["tui"]["syntax_highlighting"] = _coerce_bool(tui.get("syntax_highlighting"), True)
    normalized["tui"]["render_latex"] = _coerce_bool(tui.get("render_latex"), True)
    normalized["tui"]["enable_card_voting"] = _coerce_bool(tui.get("enable_card_voting"), True)
    normalized["tui"]["image_width"] = _coerce_int(tui.get("image_width"), 72, 1)
    normalized["tui"]["image_height"] = _coerce_int(tui.get("image_height"), 24, 1)
    if normalized["srs"]["easy_interval"] < normalized["srs"]["graduating_interval"]:
        normalized["srs"]["easy_interval"] = normalized["srs"]["graduating_interval"]
    if normalized["srs"]["max_interval"] < normalized["srs"]["easy_interval"]:
        normalized["srs"]["max_interval"] = normalized["srs"]["easy_interval"]
    return normalized


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r") as fhand:
            user_config = json.load(fhand)
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(DEFAULT_CONFIG)
    return normalize_config(user_config)


def save_config(config: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as fhand:
        json.dump(normalize_config(config), fhand, indent=2)


def reset_config() -> dict:
    config = copy.deepcopy(DEFAULT_CONFIG)
    save_config(config)
    return config
