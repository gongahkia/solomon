#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Evaluate the locked reliance-semantics corpus without persisting suggestions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from solomon.adversarial_evaluation import render_adversarial_evaluation_report, run_adversarial_dependency_evaluation
from solomon.reliance_semantics_corpus import load_reliance_semantics_corpus


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("examples/scenarios/conservative-reliance-semantics-proof/corpus/manifest.json"),
    )
    parser.add_argument("--split", choices=("all", "development", "holdout"), default="all")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    corpus = load_reliance_semantics_corpus(arguments.corpus)
    result = run_adversarial_dependency_evaluation(corpus, split=arguments.split)
    result["schema"] = "solomon.conservative_reliance_semantics_evaluation.v1"
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(_render_report(result), encoding="utf-8")
    print(json.dumps(_summary(result), indent=2, sort_keys=True))


def _render_report(result: dict[str, Any]) -> str:
    report = render_adversarial_evaluation_report(result)
    return report.replace("Adversarial Dependency Challenge", "Conservative Reliance Semantics")


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": result["schema"],
        "split": result["split"],
        "metrics": result["metrics"],
        "error_stage_distribution": result["error_stage_distribution"],
    }


if __name__ == "__main__":
    main()
