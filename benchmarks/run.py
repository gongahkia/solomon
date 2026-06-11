#!/usr/bin/env python3
"""Run Shibahama memory benchmarks."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_BINDING = ROOT / "bindings" / "python" / "python"
if PY_BINDING.exists():
    sys.path.insert(0, str(PY_BINDING))

from shibahama_bench.adapters import ADAPTERS
from shibahama_bench.metrics import (
    BenchmarkResult,
    score_answer,
    token_cost,
    write_json,
    write_markdown,
)
from shibahama_bench.tasks import load_suite


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default="currencybench")
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--systems", default="shibahama,warehouse")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/latest.json"))
    parser.add_argument("--markdown", type=Path, default=Path("benchmarks/results/latest.md"))
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args()

    cases = load_suite(args.suite, args.dataset, args.seed)
    results: list[BenchmarkResult] = []

    for system_name in [name.strip() for name in args.systems.split(",") if name.strip()]:
        adapter_cls = ADAPTERS.get(system_name)
        if adapter_cls is None:
            raise SystemExit(f"unknown system: {system_name}")

        try:
            adapter = adapter_cls()
        except Exception as error:
            if not args.allow_missing:
                raise
            results.append(
                BenchmarkResult(
                    suite=args.suite,
                    case="adapter-init",
                    system=system_name,
                    prompt="",
                    expected="",
                    forbidden=None,
                    answer=str(error),
                    latency_ms=0.0,
                    retrieval_token_cost=0,
                    correct=False,
                    stale_answer=True,
                    time_to_correction_seconds=None,
                    status="missing",
                )
            )
            continue

        for case in cases:
            adapter.reset(case.name)
            for observation in case.observations:
                adapter.ingest(observation)

            for query in case.queries:
                started = time.perf_counter()
                answer = adapter.query(query.prompt, args.top_k, query.now_unix)
                latency_ms = (time.perf_counter() - started) * 1000.0
                correct, stale = score_answer(answer, query.expected, query.forbidden)
                correction_lag = (
                    query.now_unix - query.changed_at_unix
                    if correct and query.changed_at_unix is not None
                    else None
                )
                results.append(
                    BenchmarkResult(
                        suite=case.metadata.get("suite", args.suite),
                        case=case.name,
                        system=adapter.name,
                        prompt=query.prompt,
                        expected=query.expected,
                        forbidden=query.forbidden,
                        answer=answer,
                        latency_ms=latency_ms,
                        retrieval_token_cost=token_cost(answer),
                        correct=correct,
                        stale_answer=stale,
                        time_to_correction_seconds=correction_lag,
                    )
                )

    write_json(
        args.output,
        results,
        config={
            "suite": args.suite,
            "dataset": str(args.dataset) if args.dataset else None,
            "systems": args.systems,
            "top_k": args.top_k,
            "seed": args.seed,
        },
    )
    write_markdown(args.markdown, results)
    print(f"wrote {args.output}")
    print(f"wrote {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
