from __future__ import annotations

import json
import os
import tempfile

from schema import DOCUMENT_SETS_KEY, SchemaError, normalize_document, serialize_document

CONFIG_DIR = os.path.expanduser("~/.config/senko")


def ensure_config_dir() -> str:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    return CONFIG_DIR


def sko_path(filename: str) -> str:
    ensure_config_dir()
    return os.path.join(CONFIG_DIR, filename)


def read_sko(filename: str, config: dict | None = None) -> dict:
    with open(sko_path(filename), "r") as fhand:
        raw = json.load(fhand)
    document = normalize_document(raw, config)
    return document[DOCUMENT_SETS_KEY]


def _error_message(exc: Exception) -> str:
    if isinstance(exc, SchemaError):
        return exc.errors[0]
    return str(exc)


def inspect_sko(filename: str, config: dict | None = None) -> dict:
    path = sko_path(filename)
    try:
        with open(path, "r") as fhand:
            raw = json.load(fhand)
        sets = normalize_document(raw, config)[DOCUMENT_SETS_KEY]
        return {
            "filename": filename,
            "valid": True,
            "error": "",
            "sets": sets,
        }
    except (OSError, json.JSONDecodeError, SchemaError) as exc:
        return {
            "filename": filename,
            "valid": False,
            "error": _error_message(exc),
            "sets": {},
        }


def list_sko_files(config: dict | None = None) -> list[dict]:
    config_dir = ensure_config_dir()
    statuses = []
    for filename in sorted(os.listdir(config_dir)):
        if filename.endswith(".sko"):
            statuses.append(inspect_sko(filename, config))
    return statuses


def write_sko(filename: str, sets: dict, config: dict | None = None) -> None:
    path = sko_path(filename)
    document = serialize_document(sets, config)
    directory = os.path.dirname(path)
    with tempfile.NamedTemporaryFile(
        "w",
        dir=directory,
        delete=False,
        encoding="utf-8",
    ) as tmp:
        json.dump(document, tmp, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = tmp.name
    os.replace(tmp_path, path)
