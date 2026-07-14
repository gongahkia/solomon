from __future__ import annotations

import json
import math
import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import UUID

from stonks_cli.vnext.database import SQLiteConnectionFactory
from stonks_cli.vnext.errors import VNextInvariantError
from stonks_cli.vnext.foundation import as_utc

_SNAPSHOT_KIND_PATTERN = re.compile(r"[a-z][a-z0-9._-]*\Z")
_SENSITIVE_PAYLOAD_MARKERS = ("token", "secret", "password", "authorization", "credential", "cookie")
_SNAPSHOTS_TABLE = "vnext_transactional_snapshots"


@dataclass(frozen=True)
class TransactionalSnapshot:
    snapshot_id: UUID
    kind: str
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, UUID):
            raise TypeError("transactional snapshot ID must be a UUID")
        if not isinstance(self.kind, str) or not _SNAPSHOT_KIND_PATTERN.fullmatch(self.kind):
            raise ValueError("transactional snapshot kind is invalid")
        payload = _freeze_payload(self.payload)
        if not isinstance(payload, Mapping):
            raise ValueError("transactional snapshot payload must be an object")
        object.__setattr__(self, "captured_at", as_utc(self.captured_at))
        object.__setattr__(self, "payload", payload)

    def to_data(self) -> dict[str, object]:
        return {
            "snapshot_id": str(self.snapshot_id),
            "kind": self.kind,
            "captured_at": self.captured_at.isoformat().replace("+00:00", "Z"),
            "payload": _thaw_payload(self.payload),
        }

    @classmethod
    def from_data(cls, data: object) -> TransactionalSnapshot:
        if not isinstance(data, dict) or set(data) != {"snapshot_id", "kind", "captured_at", "payload"}:
            raise ValueError("transactional snapshot fields are invalid")
        if not all(isinstance(data[field], str) for field in ("snapshot_id", "kind", "captured_at")):
            raise ValueError("transactional snapshot fields are invalid")
        try:
            return cls(UUID(data["snapshot_id"]), data["kind"], datetime.fromisoformat(data["captured_at"]), data["payload"])
        except (TypeError, ValueError) as error:
            raise ValueError("transactional snapshot is malformed") from error


@dataclass(frozen=True)
class TransactionalSnapshotStore:
    factory: SQLiteConnectionFactory

    def __post_init__(self) -> None:
        if not isinstance(self.factory, SQLiteConnectionFactory):
            raise TypeError("transactional snapshot store requires a SQLite factory")

    def initialize(self) -> None:
        with self.factory.connect() as connection:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_SNAPSHOTS_TABLE} (
                    snapshot_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def write_batch(self, snapshots: Sequence[TransactionalSnapshot]) -> None:
        if not isinstance(snapshots, Sequence) or isinstance(snapshots, (str, bytes)) or not snapshots:
            raise ValueError("transactional snapshot batch is invalid")
        if not all(isinstance(snapshot, TransactionalSnapshot) for snapshot in snapshots):
            raise TypeError("transactional snapshot batch requires snapshots")
        if len({snapshot.snapshot_id for snapshot in snapshots}) != len(snapshots):
            raise ValueError("transactional snapshot IDs must be unique")
        self.initialize()
        try:
            with self.factory.connect() as connection:
                connection.executemany(
                    f"INSERT INTO {_SNAPSHOTS_TABLE}(snapshot_id, kind, captured_at, payload_json) VALUES (?, ?, ?, ?)",
                    tuple(
                        (
                            str(snapshot.snapshot_id),
                            snapshot.kind,
                            snapshot.captured_at.isoformat().replace("+00:00", "Z"),
                            json.dumps(_thaw_payload(snapshot.payload), allow_nan=False, separators=(",", ":"), sort_keys=True),
                        )
                        for snapshot in snapshots
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise VNextInvariantError("transactional snapshot batch could not commit") from error

    def load(self, snapshot_id: UUID) -> TransactionalSnapshot | None:
        if not isinstance(snapshot_id, UUID):
            raise TypeError("transactional snapshot ID must be a UUID")
        self.initialize()
        with self.factory.connect(read_only=True) as connection:
            row = connection.execute(
                f"SELECT snapshot_id, kind, captured_at, payload_json FROM {_SNAPSHOTS_TABLE} WHERE snapshot_id = ?",
                (str(snapshot_id),),
            ).fetchone()
        if row is None:
            return None
        values = tuple(row[field] for field in ("snapshot_id", "kind", "captured_at", "payload_json"))
        if not all(isinstance(value, str) for value in values):
            raise VNextInvariantError("transactional snapshot row is malformed")
        try:
            return TransactionalSnapshot.from_data(
                {"snapshot_id": values[0], "kind": values[1], "captured_at": values[2], "payload": json.loads(values[3])}
            )
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise VNextInvariantError("transactional snapshot row is malformed") from error


def _freeze_payload(value: object, *, key: str = "") -> object:
    if any(marker in key.lower() for marker in _SENSITIVE_PAYLOAD_MARKERS):
        raise ValueError(f"transactional snapshot payload key is sensitive:{key}")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("transactional snapshot payload float must be finite")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for item_key, item_value in value.items():
            if not isinstance(item_key, str):
                raise ValueError("transactional snapshot payload keys must be strings")
            frozen[item_key] = _freeze_payload(item_value, key=item_key)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_payload(item) for item in value)
    raise ValueError("transactional snapshot payload must contain JSON-safe values")


def _thaw_payload(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_payload(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_payload(item) for item in value]
    return value
