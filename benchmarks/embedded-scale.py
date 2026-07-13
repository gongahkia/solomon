#!/usr/bin/env python3
"""Measure 100k-memory embedded Shibahama scale and recovery budgets."""

from __future__ import annotations

import argparse
import gc
import json
import os
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
except ImportError as error:  # pragma: no cover
    raise SystemExit("build the Python binding before running this benchmark") from error

from shibahama_bench.embeddings import embed_text

DEFAULT_ITEMS = 100_000
DEFAULT_QUERIES = 200
DEFAULT_WARMUP = 20
DEFAULT_P95_MS = 250.0
DEFAULT_RECOVERY_MS = 60_000.0
DEFAULT_RSS_DELTA_MIB = 1_024.0
DEFAULT_STORE_MIB = 1_024.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=int, default=DEFAULT_ITEMS)
    parser.add_argument("--queries", type=int, default=DEFAULT_QUERIES)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--dimensions", type=int, default=16)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--budget-p95-ms", type=float, default=DEFAULT_P95_MS)
    parser.add_argument("--budget-recovery-ms", type=float, default=DEFAULT_RECOVERY_MS)
    parser.add_argument("--budget-rss-delta-mib", type=float, default=DEFAULT_RSS_DELTA_MIB)
    parser.add_argument("--budget-store-mib", type=float, default=DEFAULT_STORE_MIB)
    parser.add_argument("--check-budget", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    validate_args(args)

    baseline_rss = current_rss_bytes()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "shibahama.redb"
        started = time.perf_counter()
        engine = shibahama.Shibahama(str(path), args.dimensions, capacity=args.items)
        seed_store(engine, args.items, args.dimensions)
        ingest_ms = elapsed_ms(started)
        store_bytes = database_bytes(path.parent)

        del engine
        gc.collect()
        started = time.perf_counter()
        engine = shibahama.Shibahama(str(path), args.dimensions, capacity=args.items)
        recovery_ms = elapsed_ms(started)

        vectors = [
            embed_text(query_text(index), args.dimensions)
            for index in range(args.warmup + args.queries)
        ]
        for vector in vectors[: args.warmup]:
            engine.recall(vector, args.top_k, now_unix=args.items + 1, include_cold=True)
        latencies = []
        for vector in vectors[args.warmup :]:
            started = time.perf_counter()
            engine.recall(vector, args.top_k, now_unix=args.items + 1, include_cold=True)
            latencies.append(elapsed_ms(started))
        after_rss = current_rss_bytes()

    result = summarize(args, ingest_ms, recovery_ms, latencies, baseline_rss, after_rss, store_bytes)
    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    if args.check_budget and not result["budget_passed"]:
        print("embedded scale budget exceeded", file=sys.stderr)
        return 1
    return 0


def validate_args(args: argparse.Namespace) -> None:
    for name in ("items", "queries", "dimensions", "top_k"):
        if getattr(args, name) <= 0:
            raise SystemExit(f"--{name.replace('_', '-')} must be positive")
    if args.warmup < 0:
        raise SystemExit("--warmup must be non-negative")
    for name in ("budget_p95_ms", "budget_recovery_ms", "budget_rss_delta_mib", "budget_store_mib"):
        if getattr(args, name) <= 0.0:
            raise SystemExit(f"--{name.replace('_', '-')} must be positive")


def seed_store(engine, items: int, dimensions: int) -> None:
    for index in range(items):
        content = f"Memory {index}: repo-{index % 128} route-{index % 37} decision-{index % 251}."
        engine.write(
            content,
            vector=embed_text(content, dimensions),
            source_kind="user",
            source_ref=f"embedded-scale:{index}",
            ingested_by="embedded-scale",
            valid_from_unix=index,
            ingested_at_unix=index,
        )


def query_text(index: int) -> str:
    return f"Who owns repo-{index % 128} route-{(index * 11) % 37} decision-{(index * 17) % 251}?"


def summarize(
    args: argparse.Namespace,
    ingest_ms: float,
    recovery_ms: float,
    latencies: list[float],
    baseline_rss: int,
    after_rss: int,
    store_bytes: int,
) -> dict[str, object]:
    p95 = percentile(sorted(latencies), 95.0)
    rss_delta_mib = bytes_to_mib(max(0, after_rss - baseline_rss))
    store_mib = bytes_to_mib(store_bytes)
    return {
        "benchmark": "embedded-scale",
        "items": args.items,
        "queries": args.queries,
        "warmup": args.warmup,
        "dimensions": args.dimensions,
        "top_k": args.top_k,
        "ingest_ms": ingest_ms,
        "recovery_ms": recovery_ms,
        "recall_p50_ms": statistics.median(latencies),
        "recall_p95_ms": p95,
        "rss_delta_mib": rss_delta_mib,
        "store_mib": store_mib,
        "budgets": {
            "recall_p95_ms": args.budget_p95_ms,
            "recovery_ms": args.budget_recovery_ms,
            "rss_delta_mib": args.budget_rss_delta_mib,
            "store_mib": args.budget_store_mib,
        },
        "budget_passed": p95 <= args.budget_p95_ms
        and recovery_ms <= args.budget_recovery_ms
        and rss_delta_mib <= args.budget_rss_delta_mib
        and store_mib <= args.budget_store_mib,
    }


def elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1_000.0


def database_bytes(directory: Path) -> int:
    return sum(path.stat().st_size for path in directory.iterdir() if path.is_file())


def current_rss_bytes() -> int:
    statm = Path("/proc/self/statm")
    if statm.exists():
        return int(statm.read_text(encoding="utf-8").split()[1]) * os.sysconf("SC_PAGE_SIZE")
    import resource

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss if sys.platform == "darwin" else rss * 1024


def bytes_to_mib(value: int) -> float:
    return value / (1024.0 * 1024.0)


def percentile(values: list[float], percentile_value: float) -> float:
    rank = (percentile_value / 100.0) * (len(values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] * (1.0 - (rank - lower)) + values[upper] * (rank - lower)


if __name__ == "__main__":
    raise SystemExit(main())
