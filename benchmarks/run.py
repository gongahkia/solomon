#!/usr/bin/env python3
"""Run Shibahama memory benchmarks."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_BINDING = ROOT / "bindings" / "python" / "python"
if PY_BINDING.exists():
    sys.path.insert(0, str(PY_BINDING))

from shibahama_bench.adapters import ADAPTERS, adapter_reproducibility
from shibahama_bench.metrics import (
    BenchmarkResult,
    score_answer,
    token_cost,
    write_json,
    write_markdown,
)
from shibahama_bench.tasks import load_suite


def dataset_metadata(path: Path | None) -> dict[str, object]:
    """Return reproducibility metadata for the benchmark dataset input."""

    if path is None:
        return {
            "dataset": None,
            "dataset_source": "built-in",
            "dataset_bytes": None,
            "dataset_sha256": None,
        }

    data = path.read_bytes()
    return {
        "dataset": str(path),
        "dataset_source": "external-file",
        "dataset_bytes": len(data),
        "dataset_sha256": hashlib.sha256(data).hexdigest(),
    }


def load_existing_results(path: Path) -> tuple[list[BenchmarkResult], dict[str, object]]:
    if not path.exists():
        return [], {}

    payload = json.loads(path.read_text(encoding="utf-8"))
    config = payload.get("config", {})
    results = []
    for row in payload.get("results", []):
        values = dict(row)
        values.setdefault("category", None)
        results.append(BenchmarkResult(**values))

    return results, config if isinstance(config, dict) else {}


def result_key(system: str, case: str, prompt: str) -> tuple[str, str, str]:
    return system, case, prompt


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
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--checkpoint-every", type=int, default=0)
    args = parser.parse_args()

    cases = load_suite(args.suite, args.dataset, args.seed)
    prior_results, prior_config = load_existing_results(args.output) if args.resume else ([], {})
    results: list[BenchmarkResult] = prior_results
    system_metadata: dict[str, object] = dict(prior_config.get("system_metadata", {}))
    completed = {
        result_key(result.system, result.case, result.prompt)
        for result in results
        if result.status == "ok"
    }
    command_history = list(prior_config.get("commands", []))
    command = shlex.join(sys.argv)
    if command not in command_history:
        command_history.append(command)

    def config() -> dict[str, object]:
        return {
            "command": command,
            "commands": command_history,
            "suite": args.suite,
            **dataset_metadata(args.dataset),
            "systems": args.systems,
            "top_k": args.top_k,
            "seed": args.seed,
            "embedding_model": "deterministic-blake2b for shibahama; adapter-specific values in system_metadata",
            "judge_model": None,
            "judge_prompt_hash": None,
            "scoring": "case-insensitive expected-substring match; stale if forbidden substring appears or expected is absent",
            "system_metadata": system_metadata,
        }

    def persist() -> None:
        write_json(args.output, results, config=config())
        write_markdown(args.markdown, results)

    for system_name in [name.strip() for name in args.systems.split(",") if name.strip()]:
        adapter_cls = ADAPTERS.get(system_name)
        if adapter_cls is None:
            raise SystemExit(f"unknown system: {system_name}")

        expected_keys = {
            result_key(system_name, case.name, query.prompt)
            for case in cases
            for query in case.queries
        }
        if expected_keys and expected_keys <= completed:
            continue

        try:
            adapter = adapter_cls()
            system_metadata[adapter.name] = adapter_reproducibility(adapter)
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
                    category=None,
                )
            )
            continue

        checkpoint_count = 0
        for case in cases:
            adapter.reset(case.name)
            for observation in case.observations:
                adapter.ingest(observation)

            for query in case.queries:
                key = result_key(adapter.name, case.name, query.prompt)
                if key in completed:
                    continue

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
                        category=query.category or case.metadata.get("question_type"),
                    )
                )
                completed.add(key)
                checkpoint_count += 1
                if args.checkpoint_every > 0 and checkpoint_count >= args.checkpoint_every:
                    persist()
                    checkpoint_count = 0
        persist()

    persist()
    print(f"wrote {args.output}")
    print(f"wrote {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
