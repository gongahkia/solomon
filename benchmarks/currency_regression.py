# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from solomon.evaluation import run_currency_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Solomon currency benchmark regression gate.")
    parser.add_argument("--size", type=int, default=12)
    parser.add_argument("--supersession-events", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--manifest")
    parser.add_argument("--output")
    parser.add_argument(
        "--previous-precision",
        type=float,
        default=float(os.environ.get("SOLOMON_BENCHMARK_PREVIOUS_PRECISION", "1.0")),
    )
    parser.add_argument(
        "--max-precision-drop",
        type=float,
        default=float(os.environ.get("SOLOMON_BENCHMARK_MAX_PRECISION_DROP", "0.05")),
    )
    args = parser.parse_args()
    if args.manifest is not None:
        raw_manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        manifest = raw_manifest.get("manifest", raw_manifest)
        args.size = int(manifest["corpus_size"])
        args.supersession_events = int(manifest["supersession_events"])
        args.seed = int(manifest["seed"])
    result = run_currency_benchmark(
        size=args.size,
        supersession_events=args.supersession_events,
        seed=args.seed,
        previous_precision=args.previous_precision,
        max_precision_drop=args.max_precision_drop,
    )
    payload = json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True)
    print(payload)
    if args.output is not None:
        Path(args.output).write_text(f"{payload}\n", encoding="utf-8")
    return 0 if result.passed_regression_gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
