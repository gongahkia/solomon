from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from stonks_cli.vnext.foundation import as_utc


@dataclass(frozen=True)
class ScheduledRunKey:
    job_id: str
    scheduled_for: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.job_id, str) or not self.job_id.strip():
            raise ValueError("scheduled run job ID is invalid")
        object.__setattr__(self, "scheduled_for", as_utc(self.scheduled_for))


@dataclass
class InMemoryScheduledRunDeduplicator:
    _claimed: set[ScheduledRunKey] = field(default_factory=set, init=False)

    def claim(self, key: ScheduledRunKey) -> bool:
        if not isinstance(key, ScheduledRunKey):
            raise TypeError("scheduled run key is invalid")
        if key in self._claimed:
            return False
        self._claimed.add(key)
        return True
