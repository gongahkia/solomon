from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import NewType, Protocol
from uuid import UUID, uuid4

UTCDateTime = NewType("UTCDateTime", datetime)
RUN_IDENTITY_VERSION = 1


class Clock(Protocol):
    def now(self) -> UTCDateTime: ...


def as_utc(value: object) -> UTCDateTime:
    if not isinstance(value, datetime):
        raise TypeError("timestamp must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return UTCDateTime(value.astimezone(UTC))


class SystemUTCClock:
    def now(self) -> UTCDateTime:
        return UTCDateTime(datetime.now(UTC))


@dataclass(frozen=True)
class FrozenUTCClock:
    timestamp: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", as_utc(self.timestamp))

    def now(self) -> UTCDateTime:
        return UTCDateTime(self.timestamp)


@dataclass(frozen=True)
class RunIdentity:
    run_id: UUID
    started_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "started_at", as_utc(self.started_at))

    def to_data(self) -> dict[str, object]:
        return {
            "version": RUN_IDENTITY_VERSION,
            "run_id": str(self.run_id),
            "started_at": self.started_at.isoformat().replace("+00:00", "Z"),
        }

    @classmethod
    def from_data(cls, data: object) -> RunIdentity:
        if not isinstance(data, dict) or set(data) != {"version", "run_id", "started_at"}:
            raise ValueError("invalid run identity fields")
        version = data["version"]
        run_id = data["run_id"]
        started_at = data["started_at"]
        if not isinstance(version, int) or isinstance(version, bool) or version != RUN_IDENTITY_VERSION:
            raise ValueError("unsupported run identity version")
        if not isinstance(run_id, str) or not isinstance(started_at, str):
            raise ValueError("invalid run identity data")
        try:
            return cls(UUID(run_id), datetime.fromisoformat(started_at))
        except (TypeError, ValueError) as error:
            raise ValueError("invalid run identity data") from error


def create_run_identity(clock: Clock, *, run_id: UUID | None = None) -> RunIdentity:
    return RunIdentity(run_id or uuid4(), clock.now())


def save_run_identity(path: Path, identity: RunIdentity) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(identity.to_data(), output, sort_keys=True)
        output.write("\n")


def load_run_identity(path: Path) -> RunIdentity:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("invalid run identity JSON") from error
    return RunIdentity.from_data(data)
