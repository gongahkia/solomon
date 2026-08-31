# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from solomon.adversarial_corpus import load_adversarial_dependency_corpus
from solomon.adversarial_evaluation import (
    render_adversarial_evaluation_report,
    run_adversarial_dependency_evaluation,
    run_adversarial_mutation_evaluation,
)

CORPUS = Path("examples/scenarios/adversarial-dependency-generalization-proof/corpus/manifest.json")


def test_adversarial_evaluation_reports_stage_separated_deterministic_development_results() -> None:
    result = run_adversarial_dependency_evaluation(load_adversarial_dependency_corpus(CORPUS), split="development")

    assert result["schema"] == "solomon.adversarial_dependency_evaluation.v1"
    assert result["corpus_size"] == 32
    assert result["deterministic_repeated_run"] is True
    assert result["metric_counts"]["reference_precision"]["denominator"] >= 1
    assert result["metric_counts"]["target_resolution_precision"]["denominator"] >= 1
    assert set(result["metrics"]) >= {
        "reference_precision",
        "target_resolution_precision",
        "suggestion_precision",
        "exact_evidence_span_accuracy",
        "abstention_accuracy",
        "hard_negative_false_positive_rate",
    }
    assert result["safety_invariants"]["pre_review_confirmed_edge_count"] == 0
    assert "explicit_reliance" in result["category_metrics"]
    assert "Aggregate metrics" in render_adversarial_evaluation_report(result)


def test_adversarial_mutation_evaluation_is_fixed_and_separate_from_base_metrics() -> None:
    result = run_adversarial_mutation_evaluation(load_adversarial_dependency_corpus(CORPUS))

    assert result["schema"] == "solomon.adversarial_dependency_mutation_evaluation.v1"
    assert result["mutation_count"] == 12
    assert result["deterministic_repeated_run"] is True
    assert len(result["rows"]) == 12
    assert "Mutation Evaluation" in render_adversarial_evaluation_report(result)
