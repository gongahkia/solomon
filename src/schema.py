from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from uuid import uuid4

DATE_FORMAT = "%d/%m/%Y"
SCHEMA_VERSION = 3
DOCUMENT_VERSION_KEY = "_schema_version"
DOCUMENT_SETS_KEY = "sets"
CARD_STATES = {"new", "review", "relearning"}

REQUIRED_CARD_KEYS = [
    "id",
    "card_name",
    "card_info",
    "card_add_info",
    "card_date",
    "ease_factor",
    "interval",
    "repetitions",
    "suspended",
    "tags",
    "created_at",
    "updated_at",
    "state",
    "step_index",
    "lapses",
    "again_count",
    "hard_count",
    "good_count",
    "easy_count",
]


class SchemaError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        message = "; ".join(errors)
        super().__init__(message)


def today_str() -> str:
    return date.today().strftime(DATE_FORMAT)


def timestamp_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def card_defaults(config: dict | None = None) -> dict:
    initial_ease = 2.5
    if config:
        initial_ease = config.get("srs", {}).get("initial_ease", initial_ease)
    return {
        "ease_factor": float(initial_ease),
        "interval": 0,
        "repetitions": 0,
        "suspended": False,
        "tags": [],
        "state": "new",
        "step_index": 0,
        "lapses": 0,
        "again_count": 0,
        "hard_count": 0,
        "good_count": 0,
        "easy_count": 0,
    }


def new_card(
    card_name: str = "",
    card_info: str = "",
    card_add_info: str = "",
    tags: list[str] | None = None,
    config: dict | None = None,
) -> dict:
    now = timestamp_now()
    card = {
        "id": uuid4().hex,
        "card_name": card_name,
        "card_info": card_info,
        "card_add_info": card_add_info,
        "card_date": today_str(),
        "created_at": now,
        "updated_at": now,
    }
    card.update(card_defaults(config))
    card["tags"] = _normalize_tags(tags or [])
    return card


def _normalize_tags(tags: list[str] | str | None) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        raw_tags = [part.strip() for part in tags.split(",")]
    elif isinstance(tags, list):
        raw_tags = [str(part).strip() for part in tags]
    else:
        return []
    seen = set()
    result = []
    for tag in raw_tags:
        if not tag:
            continue
        tag_key = tag.casefold()
        if tag_key in seen:
            continue
        seen.add(tag_key)
        result.append(tag)
    return result


def _validate_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def validate_card(card: dict) -> list[str]:
    errors = []
    if not isinstance(card, dict):
        return ["Card must be a JSON object."]
    for key in REQUIRED_CARD_KEYS:
        if key not in card:
            errors.append(f"Missing card field '{key}'.")
    if errors:
        return errors
    if not isinstance(card["id"], str) or not card["id"].strip():
        errors.append("Field 'id' must be a non-empty string.")
    if not isinstance(card["card_name"], str) or not card["card_name"].strip():
        errors.append("Field 'card_name' must be a non-empty string.")
    for key in ("card_info", "card_add_info"):
        if not isinstance(card[key], str):
            errors.append(f"Field '{key}' must be a string.")
    try:
        datetime.strptime(card["card_date"], DATE_FORMAT)
    except (TypeError, ValueError):
        errors.append(f"Field 'card_date' must use {DATE_FORMAT}.")
    if not isinstance(card["ease_factor"], (int, float)):
        errors.append("Field 'ease_factor' must be numeric.")
    if not isinstance(card["interval"], int) or card["interval"] < 0:
        errors.append("Field 'interval' must be a non-negative integer.")
    if not isinstance(card["repetitions"], int) or card["repetitions"] < 0:
        errors.append("Field 'repetitions' must be a non-negative integer.")
    if not isinstance(card["suspended"], bool):
        errors.append("Field 'suspended' must be a boolean.")
    if not isinstance(card["tags"], list) or any(not isinstance(tag, str) for tag in card["tags"]):
        errors.append("Field 'tags' must be a list of strings.")
    if card["state"] not in CARD_STATES:
        errors.append(f"Field 'state' must be one of {sorted(CARD_STATES)}.")
    if not isinstance(card["step_index"], int) or card["step_index"] < 0:
        errors.append("Field 'step_index' must be a non-negative integer.")
    for key in ("lapses", "again_count", "hard_count", "good_count", "easy_count"):
        if not isinstance(card[key], int) or card[key] < 0:
            errors.append(f"Field '{key}' must be a non-negative integer.")
    for key in ("created_at", "updated_at"):
        if not isinstance(card[key], str) or not _validate_timestamp(card[key]):
            errors.append(f"Field '{key}' must be an ISO timestamp string.")
    return errors


def touch_card(card: dict) -> dict:
    card["updated_at"] = timestamp_now()
    return card


def reset_card_progress(card: dict, config: dict | None = None) -> dict:
    defaults = card_defaults(config)
    card["ease_factor"] = defaults["ease_factor"]
    card["interval"] = defaults["interval"]
    card["repetitions"] = defaults["repetitions"]
    card["state"] = "new"
    card["step_index"] = 0
    card["card_date"] = today_str()
    touch_card(card)
    return card


def record_grade(card: dict, grade: int) -> dict:
    grade_map = {
        0: "again_count",
        1: "hard_count",
        2: "good_count",
        3: "easy_count",
    }
    key = grade_map[grade]
    card[key] = int(card.get(key, 0)) + 1
    return card


def is_leech(card: dict, config: dict | None = None) -> bool:
    threshold = 8
    if config:
        threshold = int(config.get("srs", {}).get("leech_threshold", threshold))
    return int(card.get("lapses", 0)) >= threshold


def _default_state(card: dict) -> str:
    if int(card.get("interval", 0)) > 0 or int(card.get("repetitions", 0)) > 0:
        return "review"
    return "new"


def migrate_card(card: dict, config: dict | None = None) -> dict:
    if not isinstance(card, dict):
        raise SchemaError(["Card must be a JSON object."])
    migrated = deepcopy(card)
    defaults = card_defaults(config)
    now = timestamp_now()
    migrated.setdefault("id", uuid4().hex)
    migrated.setdefault("card_name", "")
    migrated.setdefault("card_info", "")
    migrated.setdefault("card_add_info", "")
    migrated.setdefault("card_date", today_str())
    migrated.setdefault("created_at", now)
    migrated.setdefault("updated_at", now)
    for key, value in defaults.items():
        if key not in migrated:
            migrated[key] = deepcopy(value)
    migrated.setdefault("state", _default_state(migrated))
    migrated.setdefault("step_index", 0)
    migrated.setdefault("lapses", 0)
    migrated.setdefault("again_count", 0)
    migrated.setdefault("hard_count", 0)
    migrated.setdefault("good_count", 0)
    migrated.setdefault("easy_count", 0)
    migrated["tags"] = _normalize_tags(migrated.get("tags"))
    errors = validate_card(migrated)
    if errors:
        raise SchemaError(errors)
    return migrated


def normalize_document(raw: dict, config: dict | None = None) -> dict:
    if not isinstance(raw, dict):
        raise SchemaError(["Deck document must be a JSON object."])
    schema_version = raw.get(DOCUMENT_VERSION_KEY)
    if DOCUMENT_SETS_KEY in raw or schema_version is not None:
        if schema_version not in (None, 2, SCHEMA_VERSION):
            raise SchemaError([f"Unsupported schema version '{schema_version}'."])
        sets = raw.get(DOCUMENT_SETS_KEY)
        if not isinstance(sets, dict):
            raise SchemaError([f"Field '{DOCUMENT_SETS_KEY}' must be an object of sets."])
    else:
        sets = raw
    normalized_sets = {}
    errors = []
    for set_name, cards in sets.items():
        if not isinstance(set_name, str) or not set_name.strip():
            errors.append("Set names must be non-empty strings.")
            continue
        if not isinstance(cards, list):
            errors.append(f"Set '{set_name}' must contain a list of cards.")
            continue
        normalized_sets[set_name] = []
        for index, card in enumerate(cards):
            try:
                normalized_sets[set_name].append(migrate_card(card, config))
            except SchemaError as exc:
                for err in exc.errors:
                    errors.append(f"{set_name}[{index}]: {err}")
    if errors:
        raise SchemaError(errors)
    return serialize_document(normalized_sets)


def serialize_document(sets: dict, config: dict | None = None) -> dict:
    if not isinstance(sets, dict):
        raise SchemaError(["Sets must be a JSON object of set name to card list."])
    document_sets = {}
    errors = []
    for set_name, cards in sets.items():
        if not isinstance(set_name, str) or not set_name.strip():
            errors.append("Set names must be non-empty strings.")
            continue
        if not isinstance(cards, list):
            errors.append(f"Set '{set_name}' must contain a list of cards.")
            continue
        document_sets[set_name] = []
        for index, card in enumerate(cards):
            try:
                document_sets[set_name].append(migrate_card(card, config))
            except SchemaError as exc:
                for err in exc.errors:
                    errors.append(f"{set_name}[{index}]: {err}")
    if errors:
        raise SchemaError(errors)
    return {
        DOCUMENT_VERSION_KEY: SCHEMA_VERSION,
        DOCUMENT_SETS_KEY: document_sets,
    }


def migrate_file(sko_contents: dict, config: dict | None = None) -> dict:
    return normalize_document(sko_contents, config)[DOCUMENT_SETS_KEY]
