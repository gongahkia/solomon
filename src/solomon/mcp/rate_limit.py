# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from pydantic import Field

from solomon.api.schemas import SolomonModel


class TokenBucketConfig(SolomonModel):
    capacity: int = Field(default=60, ge=1)
    refill_per_second: float = Field(default=1.0, ge=0.0)

    @classmethod
    def from_env(cls) -> TokenBucketConfig:
        return cls(
            capacity=int(os.environ.get("SOLOMON_MCP_RATE_LIMIT_CAPACITY", "60")),
            refill_per_second=float(os.environ.get("SOLOMON_MCP_RATE_LIMIT_REFILL_PER_SECOND", "1.0")),
        )


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class TokenBucketRateLimiter:
    def __init__(self, config: TokenBucketConfig | None = None) -> None:
        self.config = config or TokenBucketConfig.from_env()
        self._buckets: dict[str, _Bucket] = {}

    def allow(self, caller_id: str | None) -> bool:
        key = caller_id or "anonymous"
        now = time.monotonic()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=float(self.config.capacity), updated_at=now)
            self._buckets[key] = bucket
        elapsed = max(0.0, now - bucket.updated_at)
        bucket.tokens = min(float(self.config.capacity), bucket.tokens + elapsed * self.config.refill_per_second)
        bucket.updated_at = now
        if bucket.tokens < 1.0:
            return False
        bucket.tokens -= 1.0
        return True


__all__ = ["TokenBucketConfig", "TokenBucketRateLimiter"]
