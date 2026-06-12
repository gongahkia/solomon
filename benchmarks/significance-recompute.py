#!/usr/bin/env python3
"""Profile significance recompute through why() over a long access history."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_BINDING = ROOT / "bindings" / "python" / "python"
if PY_BINDING.exists():
    sys.path.insert(0, str(PY_BINDING))

try:
    import shibahama
except ImportError as error:  # pragma: no cover - exercised by users without a built extension.
    raise SystemExit(
        "Shibahama Python bindings are not importable. Run "
        "`scripts/ci/python-binding-smoke.sh` or `python -m maturin develop` first."
    ) from error

from shibahama_bench.embeddings import embed_text

DEFAULT_P95_BUDGET_US = 20_000.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--access-events", type=int, default=1_000)
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--dimensions", type=int, default=16)
    parser.add_argument("--budget-p95-us", type=float, default=DEFAULT_P95_BUDGET_US)
    parser.add_argument("--check-budget", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    validate_args(args)

    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "significance.redb"
        engine = shibahama.Shibahama(str(db_path), args.dimensions, capacity=4)
        item = seed_item_with_access_history(engine, args.access_events, args.dimensions)

        for _ in range(args.warmup):
            assert engine.why(item.id, now_unix=args.access_events + 1) is not None

        latencies_us = []
        for _ in range(args.iterations):
            started = time.perf_counter()
            trace = engine.why(item.id, now_unix=args.access_events + 1)
            latencies_us.append((time.perf_counter() - started) * 1_000_000.0)
            assert trace is not None

    result = summarize(args, latencies_us)
    payload = json.dumps(result, indent=2, sort_keys=True)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")

    print(payload)

    if args.check_budget and not result["budget_passed"]:
        print(
            "significance recompute budget exceeded: "
            f"p95={result['latency_p95_us']:.3f}us budget={args.budget_p95_us:.3f}us",
            file=sys.stderr,
        )
        return 1

    return 0


def validate_args(args: argparse.Namespace) -> None:
    for field in ("access_events", "iterations", "dimensions"):
        if getattr(args, field) <= 0:
            raise SystemExit(f"--{field.replace('_', '-')} must be positive")

    if args.warmup < 0:
        raise SystemExit("--warmup must be non-negative")

    if args.budget_p95_us <= 0.0:
        raise SystemExit("--budget-p95-us must be positive")


def seed_item_with_access_history(
    engine: shibahama.Shibahama,
    access_events: int,
    dimensions: int,
) -> shibahama.MemoryItem:
    content = "Profile target: a memory with a long access history."
    item = engine.write(
        content,
        vector=embed_text(content, dimensions),
        source_kind="user",
        source_ref="significance-profile",
        ingested_by="significance-profile",
        valid_from_unix=0,
        ingested_at_unix=0,
    )
    outcomes = ("surfaced", "led_somewhere", "cited", "ignored", "contradicted")

    for index in range(access_events):
        engine.reinforce(item.id, outcomes[index % len(outcomes)])

    return item


def summarize(args: argparse.Namespace, latencies_us: list[float]) -> dict[str, object]:
    sorted_latencies = sorted(latencies_us)

    return {
        "benchmark": "significance-recompute",
        "access_events": args.access_events,
        "iterations": args.iterations,
        "warmup": args.warmup,
        "dimensions": args.dimensions,
        "latency_min_us": min(sorted_latencies),
        "latency_p50_us": statistics.median(sorted_latencies),
        "latency_p95_us": percentile(sorted_latencies, 95.0),
        "latency_max_us": max(sorted_latencies),
        "budget_p95_us": args.budget_p95_us,
        "budget_passed": percentile(sorted_latencies, 95.0) <= args.budget_p95_us,
    }


def percentile(sorted_values: list[float], percentile_value: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]

    rank = (percentile_value / 100.0) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower

    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


if __name__ == "__main__":
    raise SystemExit(main())
