# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sys
import time
from collections.abc import Callable

from solomon.api.schemas import SolomonModel
from solomon.currency.models import KnowledgeItem


class LatencyBudget(SolomonModel):
    recall_p50_ms: float = 100.0
    recall_p95_ms: float = 250.0
    propagation_p95_ms: float = 500.0


class LatencyMeasurement(SolomonModel):
    samples_ms: list[float]
    p50_ms: float
    p95_ms: float


def measure_latency(operation: Callable[[], object], *, samples: int = 5) -> LatencyMeasurement:
    timings: list[float] = []
    for _ in range(samples):
        start = time.perf_counter()
        operation()
        timings.append((time.perf_counter() - start) * 1000.0)
    ordered = sorted(timings)
    p50 = ordered[len(ordered) // 2]
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return LatencyMeasurement(samples_ms=timings, p50_ms=p50, p95_ms=p95)


def assert_recall_budget(measurement: LatencyMeasurement, budget: LatencyBudget) -> bool:
    return measurement.p50_ms <= budget.recall_p50_ms and measurement.p95_ms <= budget.recall_p95_ms


def estimate_local_memory_bytes(items: list[KnowledgeItem]) -> int:
    return sum(sys.getsizeof(item.model_dump_json()) for item in items)

