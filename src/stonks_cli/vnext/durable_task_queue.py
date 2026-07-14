from __future__ import annotations

import json
import math
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import UUID, uuid4

from stonks_cli.vnext.database import SQLiteConnectionFactory
from stonks_cli.vnext.errors import VNextInvariantError
from stonks_cli.vnext.foundation import Clock, as_utc

_TASK_NAME_PATTERN = re.compile(r"[a-z][a-z0-9._-]*\Z")
_SENSITIVE_PAYLOAD_MARKERS = ("token", "secret", "password", "authorization", "credential", "cookie")
_TASKS_TABLE = "vnext_durable_tasks"


@dataclass(frozen=True)
class DurableTask:
    task_id: UUID
    name: str
    payload: Mapping[str, object] = field(default_factory=dict)
    enqueued_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, UUID):
            raise TypeError("durable task ID must be a UUID")
        if not isinstance(self.name, str) or not _TASK_NAME_PATTERN.fullmatch(self.name):
            raise ValueError("durable task name is invalid")
        frozen_payload = _freeze_payload(self.payload)
        if not isinstance(frozen_payload, Mapping):
            raise ValueError("durable task payload must be an object")
        object.__setattr__(self, "payload", frozen_payload)
        object.__setattr__(self, "enqueued_at", as_utc(self.enqueued_at))

    def to_data(self) -> dict[str, object]:
        return {
            "task_id": str(self.task_id),
            "name": self.name,
            "payload": _thaw_payload(self.payload),
            "enqueued_at": self.enqueued_at.isoformat().replace("+00:00", "Z"),
        }

    @classmethod
    def from_data(cls, data: object) -> DurableTask:
        if not isinstance(data, dict) or set(data) != {"task_id", "name", "payload", "enqueued_at"}:
            raise ValueError("durable task fields are invalid")
        if not isinstance(data["task_id"], str) or not isinstance(data["name"], str) or not isinstance(data["enqueued_at"], str):
            raise ValueError("durable task fields are invalid")
        try:
            return cls(UUID(data["task_id"]), data["name"], data["payload"], datetime.fromisoformat(data["enqueued_at"]))
        except (TypeError, ValueError) as error:
            raise ValueError("durable task is malformed") from error


def create_durable_task(name: str, payload: Mapping[str, object], clock: Clock, *, task_id: UUID | None = None) -> DurableTask:
    if not hasattr(clock, "now") or not callable(clock.now):
        raise TypeError("durable task clock is invalid")
    return DurableTask(task_id or uuid4(), name, payload, clock.now())


@dataclass(frozen=True)
class DurableTaskQueue:
    factory: SQLiteConnectionFactory

    def __post_init__(self) -> None:
        if not isinstance(self.factory, SQLiteConnectionFactory):
            raise TypeError("durable task queue requires a SQLite factory")

    def initialize(self) -> None:
        with self.factory.connect() as connection:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_TASKS_TABLE} (
                    task_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    enqueued_at TEXT NOT NULL
                )
                """
            )

    def enqueue(self, task: DurableTask) -> None:
        if not isinstance(task, DurableTask):
            raise TypeError("durable task is required")
        self.initialize()
        try:
            with self.factory.connect() as connection:
                connection.execute(
                    f"INSERT INTO {_TASKS_TABLE}(task_id, name, payload_json, enqueued_at) VALUES (?, ?, ?, ?)",
                    (
                        str(task.task_id),
                        task.name,
                        json.dumps(_thaw_payload(task.payload), allow_nan=False, separators=(",", ":"), sort_keys=True),
                        task.enqueued_at.isoformat().replace("+00:00", "Z"),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise VNextInvariantError("durable task is already enqueued") from error

    def peek(self) -> DurableTask | None:
        self.initialize()
        with self.factory.connect(read_only=True) as connection:
            row = connection.execute(
                f"SELECT task_id, name, payload_json, enqueued_at FROM {_TASKS_TABLE} ORDER BY enqueued_at, task_id LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return _task_from_row(row)


def _task_from_row(row: sqlite3.Row) -> DurableTask:
    task_id = row["task_id"]
    name = row["name"]
    payload_json = row["payload_json"]
    enqueued_at = row["enqueued_at"]
    if not all(isinstance(value, str) for value in (task_id, name, payload_json, enqueued_at)):
        raise VNextInvariantError("durable task queue row is malformed")
    try:
        return DurableTask.from_data(
            {"task_id": task_id, "name": name, "payload": json.loads(payload_json), "enqueued_at": enqueued_at}
        )
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise VNextInvariantError("durable task queue row is malformed") from error


def _freeze_payload(value: object, *, key: str = "") -> object:
    if any(marker in key.lower() for marker in _SENSITIVE_PAYLOAD_MARKERS):
        raise ValueError(f"durable task payload key is sensitive:{key}")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("durable task payload float must be finite")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for item_key, item_value in value.items():
            if not isinstance(item_key, str):
                raise ValueError("durable task payload keys must be strings")
            frozen[item_key] = _freeze_payload(item_value, key=item_key)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_payload(item) for item in value)
    raise ValueError("durable task payload must contain JSON-safe values")


def _thaw_payload(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_payload(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_payload(item) for item in value]
    return value
