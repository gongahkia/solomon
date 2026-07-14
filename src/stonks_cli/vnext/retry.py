from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from stonks_cli.vnext.errors import VNextExternalDataError

Result = TypeVar("Result")


@dataclass(frozen=True)
class IdempotentReadRetryPolicy:
    max_attempts: int
    delays_seconds: tuple[float, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.max_attempts, int) or isinstance(self.max_attempts, bool) or self.max_attempts < 1:
            raise ValueError("idempotent read max_attempts must be positive")
        if len(self.delays_seconds) != self.max_attempts - 1:
            raise ValueError("idempotent read delays must cover each retry")
        if any(not isinstance(delay, (int, float)) or isinstance(delay, bool) or not math.isfinite(delay) or delay < 0 for delay in self.delays_seconds):
            raise ValueError("idempotent read delays must be finite non-negative numbers")


def retry_idempotent_read(
    read: Callable[[], Result],
    policy: IdempotentReadRetryPolicy,
    *,
    is_retryable: Callable[[VNextExternalDataError], bool],
    sleep: Callable[[float], None],
) -> Result:
    if not callable(read) or not isinstance(policy, IdempotentReadRetryPolicy) or not callable(is_retryable) or not callable(sleep):
        raise TypeError("idempotent read retry dependencies are required")
    for attempt in range(policy.max_attempts):
        try:
            return read()
        except VNextExternalDataError as error:
            if attempt == policy.max_attempts - 1 or not is_retryable(error):
                raise
            sleep(policy.delays_seconds[attempt])
    raise AssertionError("unreachable idempotent read retry state")
