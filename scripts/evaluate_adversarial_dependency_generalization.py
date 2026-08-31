#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Evaluate the locked adversarial dependency challenge without persisting suggestions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from solomon.adversarial_corpus import load_adversarial_dependency_corpus
from solomon.adversarial_evaluation import (
    render_adversarial_evaluation_report,
    run_adversarial_dependency_evaluation,
    run_adversarial_mutation_evaluation,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("examples/scenarios/adversarial-dependency-generalization-proof/corpus/manifest.json"),
    )
    parser.add_argument("--split", choices=("all", "development", "holdout"), default="all")
    parser.add_argument("--mutations", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    corpus = load_adversarial_dependency_corpus(arguments.corpus)
    result = (
        run_adversarial_mutation_evaluation(corpus)
        if arguments.mutations
        else run_adversarial_dependency_evaluation(corpus, split=arguments.split)
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if arguments.report is not None:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(render_adversarial_evaluation_report(result), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("schema", "metrics") if key in result}, indent=2))


if __name__ == "__main__":
    main()
