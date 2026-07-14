from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from stonks_cli.vnext.errors import OpenDQuotaExceededError, VNextInvariantError


@dataclass
class ReadOnlyRateLimiter:
    max_requests: int
    window_seconds: float
    clock: Callable[[], float] = time.monotonic
    _timestamps: deque[float] = field(default_factory=deque, init=False)
    _last_observed: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.max_requests, int) or isinstance(self.max_requests, bool) or self.max_requests < 1:
            raise ValueError("read-only rate limit must be a positive integer")
        if not isinstance(self.window_seconds, (int, float)) or isinstance(self.window_seconds, bool) or not math.isfinite(self.window_seconds) or self.window_seconds <= 0:
            raise ValueError("read-only rate-limit window must be positive and finite")
        if not callable(self.clock):
            raise TypeError("read-only rate-limit clock must be callable")

    def acquire(self) -> None:
        now = self.clock()
        if not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(now):
            raise VNextInvariantError("read-only rate-limit clock is invalid")
        now = float(now)
        if self._last_observed is not None and now < self._last_observed:
            raise VNextInvariantError("read-only rate-limit clock moved backward")
        self._last_observed = now
        while self._timestamps and self._timestamps[0] <= now - self.window_seconds:
            self._timestamps.popleft()
        if len(self._timestamps) >= self.max_requests:
            raise OpenDQuotaExceededError("read-only rate limit exceeded")
        self._timestamps.append(now)
