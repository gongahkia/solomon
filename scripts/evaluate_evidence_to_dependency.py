#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run Solomon's deterministic Evidence-to-Dependency corpus evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from solomon.evidence_evaluation import (
    load_evidence_dependency_corpus,
    render_evidence_dependency_report,
    run_evidence_dependency_evaluation,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("examples/scenarios/evidence-to-dependency-proof/corpus/manifest.json"),
    )
    parser.add_argument("--split", choices=("all", "development", "holdout"), default="all")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()

    corpus = load_evidence_dependency_corpus(arguments.corpus)
    result = run_evidence_dependency_evaluation(corpus, split=arguments.split)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if arguments.report is not None:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(render_evidence_dependency_report(result), encoding="utf-8")
    print(
        json.dumps(
            {key: result[key] for key in ("split", "corpus_size", "metrics", "error_stage_distribution")}, indent=2
        )
    )


if __name__ == "__main__":
    main()
