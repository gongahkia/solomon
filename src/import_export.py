from __future__ import annotations

import csv
import json
from copy import deepcopy

from schema import DATE_FORMAT, DOCUMENT_SETS_KEY, new_card, normalize_document, serialize_document

CSV_FIELDS = [
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
CSV_ALIASES = {
    "set_name": ["set_name", "set", "deck", "topic", "category"],
    "card_name": ["card_name", "front", "question", "prompt", "term"],
    "card_info": ["card_info", "back", "answer", "definition", "content"],
    "card_add_info": ["card_add_info", "notes", "extra", "hint"],
    "card_date": ["card_date", "due", "review_date"],
    "tags": ["tags", "labels"],
    "suspended": ["suspended", "paused"],
    "ease_factor": ["ease_factor", "ease"],
    "interval": ["interval", "days"],
    "repetitions": ["repetitions", "reviews"],
}


def import_from_txt(filepath: str, config: dict | None = None) -> dict:
    with open(filepath, "r") as fhand:
        content = fhand.read()
    blocks = content.split("---")
    result = {}
    for block in blocks:
        lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
        if not lines or not lines[0].startswith("TOPIC: "):
            continue
        set_name = lines[0][len("TOPIC: ") :].strip()
        if not set_name or len(lines) < 2:
            continue
        card = new_card(
            card_name=lines[1],
            card_info="\n".join(lines[2:]) if len(lines) > 2 else "",
            config=config,
        )
        result.setdefault(set_name, []).append(card)
    return result


def import_from_json(filepath: str, config: dict | None = None) -> dict:
    with open(filepath, "r") as fhand:
        data = json.load(fhand)
    return normalize_document(data, config)[DOCUMENT_SETS_KEY]


def infer_csv_mapping(fieldnames: list[str] | None, overrides: dict | None = None) -> tuple[dict, list[str]]:
    fieldnames = fieldnames or []
    lowered = {field.casefold(): field for field in fieldnames}
    mapping = {}
    overrides = overrides or {}
    for target, aliases in CSV_ALIASES.items():
        override = overrides.get(target)
        if override in fieldnames:
            mapping[target] = override
            continue
        for alias in aliases:
            if alias.casefold() in lowered:
                mapping[target] = lowered[alias.casefold()]
                break
    missing = [field for field in ("set_name", "card_name") if field not in mapping]
    return mapping, missing


def import_from_csv(filepath: str, config: dict | None = None, field_mapping: dict | None = None) -> dict:
    result = {}
    with open(filepath, "r", newline="") as fhand:
        reader = csv.DictReader(fhand)
        mapping, missing = infer_csv_mapping(reader.fieldnames, field_mapping)
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")
        for row_number, row in enumerate(reader, start=2):
            set_name = (row.get(mapping["set_name"]) or "").strip()
            card_name = (row.get(mapping["card_name"]) or "").strip()
            if not set_name or not card_name:
                raise ValueError(f"Row {row_number} is missing set_name or card_name.")
            card = new_card(
                card_name=card_name,
                card_info=row.get(mapping.get("card_info", ""), "") or "",
                card_add_info=row.get(mapping.get("card_add_info", ""), "") or "",
                tags=row.get(mapping.get("tags", ""), "") or "",
                config=config,
            )
            date_field = mapping.get("card_date")
            if date_field and row.get(date_field):
                card["card_date"] = row[date_field].strip()
            suspended_field = mapping.get("suspended")
            if suspended_field and row.get(suspended_field):
                card["suspended"] = row[suspended_field].strip().lower() in {"1", "true", "yes", "y"}
            for field in ("ease_factor",):
                source = mapping.get(field)
                value = (row.get(source) or "").strip() if source else ""
                if value:
                    card[field] = float(value)
            for field in ("interval", "repetitions"):
                source = mapping.get(field)
                value = (row.get(source) or "").strip() if source else ""
                if value:
                    card[field] = int(value)
            result.setdefault(set_name, []).append(card)
    return normalize_document(result, config)[DOCUMENT_SETS_KEY]


def export_to_json(sko_contents: dict, filepath: str, config: dict | None = None) -> None:
    with open(filepath, "w") as fhand:
        json.dump(serialize_document(sko_contents, config), fhand, indent=2)


def export_to_txt(sko_contents: dict, filepath: str) -> None:
    with open(filepath, "w") as fhand:
        for set_name, cards in sko_contents.items():
            for card in cards:
                fhand.write("---\n")
                fhand.write(f"TOPIC: {set_name}\n")
                fhand.write(f"{card.get('card_name', '')}\n")
                info = card.get("card_info", "")
                if info:
                    fhand.write(f"{info}\n")
                add_info = card.get("card_add_info", "")
                if add_info:
                    fhand.write(f"{add_info}\n")
        fhand.write("---\n")


def export_to_csv(sko_contents: dict, filepath: str) -> None:
    with open(filepath, "w", newline="") as fhand:
        writer = csv.DictWriter(fhand, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for set_name, cards in sko_contents.items():
            for card in cards:
                writer.writerow(
                    {
                        "set_name": set_name,
                        "card_name": card.get("card_name", ""),
                        "card_info": card.get("card_info", ""),
                        "card_add_info": card.get("card_add_info", ""),
                        "card_date": card.get("card_date", ""),
                        "tags": ",".join(card.get("tags", [])),
                        "suspended": str(card.get("suspended", False)).lower(),
                        "ease_factor": card.get("ease_factor", ""),
                        "interval": card.get("interval", ""),
                        "repetitions": card.get("repetitions", ""),
                    }
                )


def _duplicate_key(card: dict) -> str:
    return (card.get("card_name") or "").strip().casefold()


def count_duplicates(existing: dict, incoming: dict) -> int:
    duplicates = 0
    for set_name, cards in incoming.items():
        existing_keys = {_duplicate_key(card) for card in existing.get(set_name, []) if _duplicate_key(card)}
        for card in cards:
            key = _duplicate_key(card)
            if key and key in existing_keys:
                duplicates += 1
    return duplicates


def preview_import(data: dict, existing: dict | None = None) -> dict:
    existing = existing or {}
    card_count = sum(len(cards) for cards in data.values())
    duplicate_count = count_duplicates(existing, data) if existing else 0
    set_names = sorted(data.keys())
    return {
        "set_count": len(set_names),
        "card_count": card_count,
        "duplicate_count": duplicate_count,
        "sets": [(set_name, len(data[set_name])) for set_name in set_names],
    }


def merge_sets(existing: dict, incoming: dict, strategy: str = "skip") -> tuple[dict, dict]:
    merged = deepcopy(existing)
    summary = {"added": 0, "skipped": 0, "replaced": 0, "replaced_sets": 0}
    for set_name, cards in incoming.items():
        if strategy == "replace_set":
            merged[set_name] = [deepcopy(card) for card in cards]
            summary["replaced_sets"] += 1
            summary["added"] += len(cards)
            continue
        target = merged.setdefault(set_name, [])
        key_index = {
            _duplicate_key(card): index
            for index, card in enumerate(target)
            if _duplicate_key(card)
        }
        for card in cards:
            key = _duplicate_key(card)
            if key and key in key_index:
                if strategy == "skip":
                    summary["skipped"] += 1
                    continue
                if strategy == "replace":
                    target[key_index[key]] = deepcopy(card)
                    summary["replaced"] += 1
                    continue
            target.append(deepcopy(card))
            if key:
                key_index[key] = len(target) - 1
            summary["added"] += 1
    return merged, summary
