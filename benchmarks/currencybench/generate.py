#!/usr/bin/env python3
"""Generate the deterministic CurrencyBench JSONL dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / "benchmarks"
if str(BENCHMARKS) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS))

from shibahama_bench.tasks import BenchmarkCase, currencybench

DEFAULT_OUTPUT = ROOT / "benchmarks" / "currencybench" / "currencybench-v0.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    cases = currencybench(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(case_to_record(case), sort_keys=True) + "\n" for case in cases),
        encoding="utf-8",
    )
    print(f"wrote {args.output}")
    return 0


def case_to_record(case: BenchmarkCase) -> dict[str, object]:
    return {
        "name": case.name,
        "metadata": case.metadata,
        "observations": [
            {
                "content": observation.content,
                "valid_from_unix": observation.valid_from_unix,
                "source_ref": observation.source_ref,
                "supersedes_source_ref": observation.supersedes_source_ref,
                "reinforce_count": observation.reinforce_count,
                "related_source_refs": list(observation.related_source_refs),
            }
            for observation in case.observations
        ],
        "queries": [
            {
                "prompt": query.prompt,
                "expected": query.expected,
                "forbidden": query.forbidden,
                "now_unix": query.now_unix,
                "changed_at_unix": query.changed_at_unix,
            }
            for query in case.queries
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
