# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pytest

from solomon.adversarial_corpus import load_adversarial_dependency_corpus
from solomon.adversarial_evaluation import (
    _root_cause,
    _score_predictions,
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


def test_adversarial_evaluator_validates_split_and_records_span_and_false_positive_stages() -> None:
    corpus = load_adversarial_dependency_corpus(CORPUS)
    with pytest.raises(ValueError, match="unsupported challenge split"):
        run_adversarial_dependency_evaluation(corpus, split="invalid")

    item = {
        "id": "synthetic",
        "semantic_category": "wrong_authority_near_cue",
        "label": "Depends",
        "reference_spans": [{"target_id": "target", "text": "Authority 1"}],
        "expected_suggestions": [
            {"target_id": "target", "source_span": "expected source", "target_span": "Authority 1"}
        ],
    }
    prediction = {
        "id": "synthetic",
        "references": [{"target_id": "target", "span": "Authority 1"}],
        "suggestions": [
            {"target_id": "target", "source_span": "different source", "target_span": "different authority"},
            {"target_id": "extra", "source_span": "candidate", "target_span": "candidate"},
        ],
    }

    result = _score_predictions([item], [prediction])

    assert result["error_stage_distribution"] == {
        "evidence_span_over_broad": 1,
        "wrong_authority_associated_with_cue": 1,
    }
    assert _root_cause("normalization_failure") == "deterministic evaluation discrepancy requires manual classification"
