#!/usr/bin/env python3
"""Measure embedded Shibahama resident memory against a local budget."""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import tempfile
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

DEFAULT_RSS_DELTA_BUDGET_MIB = 128.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=int, default=1_000)
    parser.add_argument("--dimensions", type=int, default=16)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--capacity", type=int)
    parser.add_argument(
        "--budget-rss-delta-mib",
        type=float,
        default=DEFAULT_RSS_DELTA_BUDGET_MIB,
    )
    parser.add_argument("--check-budget", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    validate_args(args)

    capacity = args.capacity or args.items
    gc.collect()
    baseline_rss = current_rss_bytes()

    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "memory.redb"
        engine = shibahama.Shibahama(str(db_path), args.dimensions, capacity=capacity)
        seed_store(engine, args.items, args.dimensions)
        engine.recall(
            embed_text(query_text(args.items // 2), args.dimensions),
            args.top_k,
            now_unix=args.items + 1,
            include_cold=True,
        )
        gc.collect()
        after_seed_rss = current_rss_bytes()
        database_bytes = sum(
            path.stat().st_size for path in db_path.parent.iterdir() if path.is_file()
        )

    result = summarize(args, capacity, baseline_rss, after_seed_rss, database_bytes)
    payload = json.dumps(result, indent=2, sort_keys=True)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")

    print(payload)

    if args.check_budget and not result["budget_passed"]:
        print(
            "embedded memory budget exceeded: "
            f"rss_delta={result['rss_delta_mib']:.3f}MiB "
            f"budget={result['budget_rss_delta_mib']:.3f}MiB",
            file=sys.stderr,
        )
        return 1

    return 0


def validate_args(args: argparse.Namespace) -> None:
    for field in ("items", "dimensions", "top_k"):
        if getattr(args, field) <= 0:
            raise SystemExit(f"--{field.replace('_', '-')} must be positive")

    if args.capacity is not None and args.capacity <= 0:
        raise SystemExit("--capacity must be positive")

    if args.budget_rss_delta_mib <= 0.0:
        raise SystemExit("--budget-rss-delta-mib must be positive")


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
            source_ref=f"memory-footprint:{index}",
            ingested_by="memory-footprint",
            valid_from_unix=index,
            ingested_at_unix=index,
        )


def query_text(index: int) -> str:
    return (
        f"Who owns project-{index % 32} route-{(index * 7) % 17} "
        f"decision token-{(index * 13) % 101}?"
    )


def summarize(
    args: argparse.Namespace,
    capacity: int,
    baseline_rss: int,
    after_seed_rss: int,
    database_bytes: int,
) -> dict[str, object]:
    rss_delta = max(0, after_seed_rss - baseline_rss)

    return {
        "benchmark": "memory-footprint",
        "items": args.items,
        "dimensions": args.dimensions,
        "top_k": args.top_k,
        "capacity": capacity,
        "rss_baseline_mib": bytes_to_mib(baseline_rss),
        "rss_after_seed_mib": bytes_to_mib(after_seed_rss),
        "rss_delta_mib": bytes_to_mib(rss_delta),
        "database_mib": bytes_to_mib(database_bytes),
        "budget_rss_delta_mib": args.budget_rss_delta_mib,
        "budget_passed": bytes_to_mib(rss_delta) <= args.budget_rss_delta_mib,
    }


def current_rss_bytes() -> int:
    statm = Path("/proc/self/statm")

    if statm.exists():
        resident_pages = int(statm.read_text(encoding="utf-8").split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")

    import resource

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return rss

    return rss * 1024


def bytes_to_mib(value: int) -> float:
    return value / (1024.0 * 1024.0)


if __name__ == "__main__":
    raise SystemExit(main())
