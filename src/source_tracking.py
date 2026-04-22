from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime

from import_export import import_from_csv, import_from_json, merge_sets
from storage import ensure_config_dir, read_sko, write_sko

TRACKING_FILENAME = "deck_sources.json"
TRACKING_VERSION = 1


def _tracking_path() -> str:
    return os.path.join(ensure_config_dir(), TRACKING_FILENAME)


def _load_tracking() -> dict:
    path = _tracking_path()
    try:
        with open(path, "r", encoding="utf-8") as fhand:
            raw = json.load(fhand)
        if not isinstance(raw, dict):
            raise ValueError("Invalid tracking document.")
    except (OSError, json.JSONDecodeError, ValueError):
        return {"_version": TRACKING_VERSION, "decks": {}}
    raw.setdefault("_version", TRACKING_VERSION)
    decks = raw.get("decks")
    if not isinstance(decks, dict):
        raw["decks"] = {}
    return raw


def _save_tracking(document: dict) -> None:
    with open(_tracking_path(), "w", encoding="utf-8") as fhand:
        json.dump(document, fhand, indent=2)


def _hash_file(path: str) -> str:
    digest = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as fhand:
        while True:
            chunk = fhand.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def register_deck_source(
    deck_name: str,
    source_path: str,
    *,
    strategy: str = "replace_set",
    field_mapping: dict | None = None,
) -> None:
    normalized_path = _normalize_path(source_path)
    if not os.path.isfile(normalized_path):
        return
    document = _load_tracking()
    entry = {
        "source_path": normalized_path,
        "source_hash": _hash_file(normalized_path),
        "strategy": strategy,
        "field_mapping": field_mapping or None,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    document["decks"][deck_name] = entry
    _save_tracking(document)


def tracked_source(deck_name: str) -> dict | None:
    document = _load_tracking()
    entry = document.get("decks", {}).get(deck_name)
    if not isinstance(entry, dict):
        return None
    return dict(entry)


def source_change_status(deck_name: str) -> dict:
    entry = tracked_source(deck_name)
    if not entry:
        return {"tracked": False, "changed": False, "reason": "", "entry": None}
    source_path = entry.get("source_path")
    if not isinstance(source_path, str) or not source_path:
        return {"tracked": True, "changed": False, "reason": "", "entry": entry}
    if not os.path.isfile(source_path):
        return {
            "tracked": True,
            "changed": True,
            "reason": "Tracked source file no longer exists.",
            "entry": entry,
        }
    current_hash = _hash_file(source_path)
    if current_hash != entry.get("source_hash"):
        return {
            "tracked": True,
            "changed": True,
            "reason": "Tracked source file has changed since last import.",
            "entry": entry,
            "current_hash": current_hash,
        }
    return {"tracked": True, "changed": False, "reason": "", "entry": entry}


def reload_deck_from_tracked_source(deck_name: str, config: dict | None = None) -> dict:
    entry = tracked_source(deck_name)
    if not entry:
        raise ValueError("No tracked import source for this deck.")
    source_path = entry.get("source_path")
    if not isinstance(source_path, str) or not source_path or not os.path.isfile(source_path):
        raise ValueError("Tracked source file is unavailable.")
    if source_path.endswith(".csv"):
        incoming = import_from_csv(source_path, config, field_mapping=entry.get("field_mapping"))
    elif source_path.endswith(".json") or source_path.endswith(".sko"):
        incoming = import_from_json(source_path, config)
    else:
        raise ValueError("Tracked source has unsupported file type.")
    strategy = entry.get("strategy") or "replace_set"
    existing = read_sko(deck_name, config)
    merged, summary = merge_sets(existing, incoming, strategy)
    write_sko(deck_name, merged, config)
    register_deck_source(
        deck_name,
        source_path,
        strategy=strategy,
        field_mapping=entry.get("field_mapping"),
    )
    return {"summary": summary, "strategy": strategy, "source_path": source_path}
