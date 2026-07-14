from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NewType, Protocol

UTCDateTime = NewType("UTCDateTime", datetime)


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
