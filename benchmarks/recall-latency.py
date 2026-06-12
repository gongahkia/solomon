#!/usr/bin/env python3
"""Measure embedded Shibahama recall latency against a local budget."""

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

DEFAULT_P50_BUDGET_MS = 25.0
DEFAULT_P95_BUDGET_MS = 75.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=int, default=1_000)
    parser.add_argument("--queries", type=int, default=200)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--dimensions", type=int, default=16)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--budget-p50-ms", type=float, default=DEFAULT_P50_BUDGET_MS)
    parser.add_argument("--budget-p95-ms", type=float, default=DEFAULT_P95_BUDGET_MS)
    parser.add_argument("--check-budget", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    validate_args(args)

    with tempfile.NamedTemporaryFile() as db:
        engine = shibahama.Shibahama(db.name, args.dimensions, capacity=args.items)
        seed_store(engine, args.items, args.dimensions)
        query_vectors = [
            embed_text(query_text(index), args.dimensions)
            for index in range(args.warmup + args.queries)
        ]

        for vector in query_vectors[: args.warmup]:
            engine.recall(vector, args.top_k, now_unix=args.items + 1, include_cold=True)

        latencies_ms = []
        for vector in query_vectors[args.warmup :]:
            started = time.perf_counter()
            engine.recall(vector, args.top_k, now_unix=args.items + 1, include_cold=True)
            latencies_ms.append((time.perf_counter() - started) * 1_000.0)

    result = summarize(args, latencies_ms)
    payload = json.dumps(result, indent=2, sort_keys=True)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")

    print(payload)

    if args.check_budget and (
        result["latency_p50_ms"] > args.budget_p50_ms
        or result["latency_p95_ms"] > args.budget_p95_ms
    ):
        print(
            "recall latency budget exceeded: "
            f"p50={result['latency_p50_ms']:.3f}ms budget={args.budget_p50_ms:.3f}ms, "
            f"p95={result['latency_p95_ms']:.3f}ms budget={args.budget_p95_ms:.3f}ms",
            file=sys.stderr,
        )
        return 1

    return 0


def validate_args(args: argparse.Namespace) -> None:
    for field in ("items", "queries", "dimensions", "top_k"):
        if getattr(args, field) <= 0:
            raise SystemExit(f"--{field.replace('_', '-')} must be positive")

    if args.warmup < 0:
        raise SystemExit("--warmup must be non-negative")


def seed_store(engine: shibahama.Shibahama, items: int, dimensions: int) -> None:
    for index in range(items):
        content = (
            f"Memory {index}: project-{index % 32} owns route-{index % 17} "
            f"with decision token-{index % 101}."
        )
        engine.write(
            content,
            vector=embed_text(content, dimensions),
            source_kind="user",
            source_ref=f"latency:{index}",
            ingested_by="recall-latency",
            valid_from_unix=index,
            ingested_at_unix=index,
        )


def query_text(index: int) -> str:
    return (
        f"Who owns project-{index % 32} route-{(index * 7) % 17} "
        f"decision token-{(index * 13) % 101}?"
    )


def summarize(args: argparse.Namespace, latencies_ms: list[float]) -> dict[str, object]:
    sorted_latencies = sorted(latencies_ms)

    return {
        "benchmark": "recall-latency",
        "items": args.items,
        "queries": args.queries,
        "warmup": args.warmup,
        "dimensions": args.dimensions,
        "top_k": args.top_k,
        "latency_min_ms": min(sorted_latencies),
        "latency_p50_ms": statistics.median(sorted_latencies),
        "latency_p95_ms": percentile(sorted_latencies, 95.0),
        "latency_max_ms": max(sorted_latencies),
        "budget_p50_ms": args.budget_p50_ms,
        "budget_p95_ms": args.budget_p95_ms,
        "budget_passed": statistics.median(sorted_latencies) <= args.budget_p50_ms
        and percentile(sorted_latencies, 95.0) <= args.budget_p95_ms,
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
