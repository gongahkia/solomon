from __future__ import annotations

import os
from datetime import datetime

from import_export import import_from_csv, import_from_json
from storage import read_sko, write_sko


def deck_name(name: str) -> str:
    return name if name.endswith(".sko") else f"{name}.sko"


def parse_mapping(entries: list[str]) -> dict:
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


def parse_timestamp(value: str | None, label: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {label} timestamp '{value}'. Use ISO-8601.") from exc


def history_filters(args) -> dict:
    return {
        "deck_name": deck_name(args.deck) if getattr(args, "deck", None) else None,
        "set_name": getattr(args, "set_name", None),
        "card_id": getattr(args, "card_id", None),
        "since": parse_timestamp(getattr(args, "since", None), "--since"),
        "before": parse_timestamp(getattr(args, "before", None), "--before"),
    }


def history_scope_requested(args) -> bool:
    return bool(
        getattr(args, "all", False)
        or getattr(args, "deck", None)
        or getattr(args, "set_name", None)
        or getattr(args, "card_id", None)
        or getattr(args, "since", None)
        or getattr(args, "before", None)
    )


def load_external_data(path: str, config: dict, field_mapping: dict | None = None) -> dict:
    if path.endswith(".csv"):
        return import_from_csv(path, config, field_mapping=field_mapping)
    if path.endswith(".json") or path.endswith(".sko"):
        return import_from_json(path, config)
    raise ValueError("Unsupported input file type. Use .csv, .json, or .sko.")


def load_managed_deck(name: str, config: dict) -> tuple[str, dict]:
    normalized = deck_name(name)
    return normalized, read_sko(normalized, config)


def save_managed_deck(name: str, sets: dict, config: dict) -> None:
    write_sko(deck_name(name), sets, config)


def require_set(sets: dict, set_name: str) -> list[dict]:
    if set_name not in sets:
        raise ValueError(f"Set not found: {set_name}")
    return sets[set_name]


def find_card(cards: list[dict], selector: str) -> tuple[int, dict]:
    exact_id_matches = [(index, card) for index, card in enumerate(cards) if card.get("id") == selector]
    if exact_id_matches:
        return exact_id_matches[0]
    name_matches = [
        (index, card)
        for index, card in enumerate(cards)
        if (card.get("card_name", "") or "").casefold() == selector.casefold()
    ]
    if not name_matches:
        raise ValueError(f"Card not found: {selector}")
    if len(name_matches) > 1:
        raise ValueError(f"Card selector '{selector}' is ambiguous; use a card id instead.")
    return name_matches[0]


def print_lines(lines: list[str]) -> None:
    for line in lines:
        print(line)
