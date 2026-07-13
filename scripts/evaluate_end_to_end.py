# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
from pathlib import Path

from solomon.evaluation import load_end_to_end_evaluation_corpus, run_end_to_end_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the deterministic Solomon end-to-end evaluation harness.")
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("docs/evaluation-corpus.e2e.synthetic.json"),
        help="Versioned public synthetic corpus path.",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON result path.")
    arguments = parser.parse_args()
    corpus = load_end_to_end_evaluation_corpus(arguments.corpus)
    result = run_end_to_end_evaluation(corpus.cases)
    payload = result.model_dump(mode="json")
    if arguments.output is not None:
        arguments.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
