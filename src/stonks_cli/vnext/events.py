from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID, uuid4

from stonks_cli.vnext.foundation import Clock, RunIdentity, as_utc

_EVENT_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_.]*\Z")
_SENSITIVE_PAYLOAD_MARKERS = ("token", "secret", "password", "authorization", "credential", "cookie")
EVENT_SCHEMA_VERSION = 1


class EventSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class StructuredEvent:
    event_id: UUID
    run_id: UUID
    occurred_at: datetime
    name: str
    severity: EventSeverity
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, UUID) or not isinstance(self.run_id, UUID):
            raise TypeError("event and run IDs must be UUIDs")
        if not isinstance(self.name, str) or not _EVENT_NAME_PATTERN.fullmatch(self.name):
            raise ValueError("invalid event name")
        if not isinstance(self.severity, EventSeverity):
            raise TypeError("event severity must be an EventSeverity")
        frozen_payload = _freeze_json(self.payload)
        if not isinstance(frozen_payload, Mapping):
            raise ValueError("event payload must be an object")
        object.__setattr__(self, "occurred_at", as_utc(self.occurred_at))
        object.__setattr__(self, "payload", frozen_payload)


def create_structured_event(
    clock: Clock,
    run: RunIdentity,
    *,
    name: str,
    severity: EventSeverity = EventSeverity.INFO,
    payload: Mapping[str, object] | None = None,
    event_id: UUID | None = None,
) -> StructuredEvent:
    return StructuredEvent(event_id or uuid4(), run.run_id, clock.now(), name, severity, payload or {})


def serialize_structured_event(event: StructuredEvent) -> str:
    if not isinstance(event, StructuredEvent):
        raise TypeError("structured event is required")
    data = {
        "version": EVENT_SCHEMA_VERSION,
        "event_id": str(event.event_id),
        "run_id": str(event.run_id),
        "occurred_at": event.occurred_at.isoformat().replace("+00:00", "Z"),
        "name": event.name,
        "severity": event.severity.value,
        "payload": _thaw_json(event.payload),
    }
    return json.dumps(data, allow_nan=False, separators=(",", ":"), sort_keys=True)


def deserialize_structured_event(value: object) -> StructuredEvent:
    if not isinstance(value, str):
        raise TypeError("serialized event must be a string")
    try:
        data = json.loads(value)
        if not isinstance(data, dict) or set(data) != {
            "version",
            "event_id",
            "run_id",
            "occurred_at",
            "name",
            "severity",
            "payload",
        }:
            raise ValueError("invalid event fields")
        if not isinstance(data["version"], int) or isinstance(data["version"], bool) or data["version"] != EVENT_SCHEMA_VERSION:
            raise ValueError("unsupported event version")
        if not all(isinstance(data[field], str) for field in ("event_id", "run_id", "occurred_at", "name", "severity")):
            raise ValueError("invalid event field types")
        if not isinstance(data["payload"], dict):
            raise ValueError("event payload must be an object")
        return StructuredEvent(
            UUID(data["event_id"]),
            UUID(data["run_id"]),
            datetime.fromisoformat(data["occurred_at"]),
            data["name"],
            EventSeverity(data["severity"]),
            data["payload"],
        )
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("invalid serialized event") from error


def _freeze_json(value: object, *, key: str = "") -> object:
    if _is_sensitive_key(key):
        raise ValueError(f"sensitive event payload key:{key}")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("event payload float must be finite")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for item_key, item_value in value.items():
            if not isinstance(item_key, str):
                raise ValueError("event payload keys must be strings")
            frozen[item_key] = _freeze_json(item_value, key=item_key)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    raise ValueError("event payload must contain JSON-safe values")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    return any(marker in key.lower() for marker in _SENSITIVE_PAYLOAD_MARKERS)
