# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from solomon.currency.models import CurrencyState
from solomon.graph.propagation import CurrencyPropagator
from solomon.performance import LatencyMeasurement

AUTHORITY_ID = "benchmark-authority"
TIMESTAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _BenchmarkItem:
    id: str
    currency_state: CurrencyState = CurrencyState.LIVE
    metadata: dict[str, Any] = field(default_factory=dict)

    def model_copy(self, *, update: dict[str, Any]) -> _BenchmarkItem:
        return replace(self, **update)


class _BenchmarkStore:
    def __init__(self, item_ids: set[str]) -> None:
        self.item_ids = item_ids

    def get_item(self, item_id: str) -> _BenchmarkItem:
        if item_id not in self.item_ids:
            raise KeyError(item_id)
        return _BenchmarkItem(
            id=item_id,
            metadata={},
        )

    def update_item(
        self,
        item: _BenchmarkItem,
        *,
        event_type: str = "knowledge_item_updated",
        occurred_at: datetime | None = None,
    ) -> _BenchmarkItem:
        _ = event_type, occurred_at
        self.item_ids.remove(item.id)
        return item


@dataclass(frozen=True)
class _Edge:
    id: str
    source_id: str
    target_id: str


class _FanoutGraph:
    def __init__(self, edges: list[_Edge]) -> None:
        self.dependents: dict[str, list[_Edge]] = {}
        for edge in edges:
            self.dependents.setdefault(edge.target_id, []).append(edge)

    def get_dependents(self, authority_or_item_id: str, *, at: datetime | None = None) -> list[_Edge]:
        _ = at
        return self.dependents.get(authority_or_item_id, [])


def _build_fixture(size: int, *, progress: bool) -> tuple[_BenchmarkStore, _FanoutGraph]:
    item_ids: set[str] = set()
    edges: list[_Edge] = []
    for index in range(size):
        if progress and index and index % 10000 == 0:
            print(f"fixture items: {index}/{size}", file=sys.stderr, flush=True)
        item_id = f"item-{index:06d}"
        item_ids.add(item_id)
        edges.append(
            _Edge(
                id=f"edge-{index:06d}",
                source_id=item_id,
                target_id=AUTHORITY_ID,
            )
        )
    return _BenchmarkStore(item_ids), _FanoutGraph(edges)


def measure_propagation(size: int, samples: int, *, progress: bool) -> dict[str, Any]:
    sample_measurements: list[float] = []
    for _ in range(samples):
        store, graph = _build_fixture(size, progress=progress)
        propagator = CurrencyPropagator(graph=graph, store=store)  # type: ignore[arg-type]
        start = time.perf_counter()
        impact = propagator.propagate_dependency_change(
            AUTHORITY_ID,
            changed_at=TIMESTAMP,
            reason="benchmark authority change",
            collect_reasons=False,
            record_verification_events=False,
            record_staleness_metadata=False,
        )
        sample_measurements.append((time.perf_counter() - start) * 1000.0)
        if len(impact.stale_item_ids) != size:
            raise RuntimeError(f"expected {size} stale items, got {len(impact.stale_item_ids)}")
    ordered = sorted(sample_measurements)
    measurement = LatencyMeasurement(
        samples_ms=sample_measurements,
        p50_ms=ordered[len(ordered) // 2],
        p95_ms=ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
    )
    return {"item_count": size, "measurement": measurement.model_dump(mode="json")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark dependency propagation at representative graph sizes.")
    parser.add_argument("--sizes", default="1000,10000,100000")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--max-p95-ms", type=float)
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()
    sizes = [int(value) for value in args.sizes.split(",")]
    if not sizes or any(size < 1 for size in sizes) or args.samples < 1:
        raise SystemExit("sizes and samples must be positive")
    results: list[dict[str, Any]] = [measure_propagation(size, args.samples, progress=args.progress) for size in sizes]
    payload = {"benchmark": "dependency_propagation", "authority_id": AUTHORITY_ID, "results": results}
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.max_p95_ms is not None:
        over_budget = [result for result in results if result["measurement"]["p95_ms"] > args.max_p95_ms]
        if over_budget:
            raise SystemExit(f"dependency propagation p95 exceeded {args.max_p95_ms}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
