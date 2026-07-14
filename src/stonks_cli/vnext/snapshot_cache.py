from __future__ import annotations

import math
import time
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from stonks_cli.vnext.errors import VNextInvariantError

Key = TypeVar("Key", bound=Hashable)
Value = TypeVar("Value")


@dataclass
class IdempotentSnapshotCache(Generic[Key, Value]):
    ttl_seconds: float
    clock: Callable[[], float] = time.monotonic
    _entries: dict[Key, tuple[float, Value]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.ttl_seconds, (int, float)) or isinstance(self.ttl_seconds, bool) or not math.isfinite(self.ttl_seconds) or self.ttl_seconds <= 0:
            raise ValueError("snapshot cache TTL must be positive and finite")
        if not callable(self.clock):
            raise TypeError("snapshot cache clock must be callable")

    def get_or_load(self, key: Key, load: Callable[[], Value]) -> Value:
        if not callable(load):
            raise TypeError("snapshot cache loader must be callable")
        now = self._now()
        cached = self._entries.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
        value = load()
        self._entries[key] = (now + self.ttl_seconds, value)
        return value

    def _now(self) -> float:
        now = self.clock()
        if not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(now):
            raise VNextInvariantError("snapshot cache clock is invalid")
        return float(now)
