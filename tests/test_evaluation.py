# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from solomon.currency.models import CurrencyState
from solomon.evaluation import (
    AblationConfig,
    EvaluationMetrics,
    boundary_fidelity_eval,
    decay_baseline,
    default_external_law_monitor_cases,
    evaluate_ablation,
    export_synthetic_corpus,
    generate_jurisdiction_coverage_cases,
    generate_synthetic_corpus,
    impact_query_recall,
    render_results_table,
    run_boundary_fidelity_suite,
    run_currency_evaluation,
    run_external_law_monitoring_benchmark,
    run_jurisdiction_coverage_benchmark,
    stale_surface_rate,
    time_to_flag,
    tune_recall_weights,
    warehouse_similarity_baseline,
    write_synthetic_corpus,
)
from solomon.orchestrator.retrieval import RecallWeights


def test_synthetic_corpus_and_metrics() -> None:
    corpus = generate_synthetic_corpus(size=6)
    stale_item = corpus.items[0].model_copy(update={"currency_state": CurrencyState.STALE_PENDING_REVERIFICATION})

    assert corpus.expected_stale_item_ids == {"item-0", "item-2", "item-4"}
    assert stale_surface_rate([stale_item, corpus.items[1]]) == 0.5
    assert time_to_flag(
        datetime(2025, 1, 1, tzinfo=timezone.utc),
        datetime(2025, 1, 1, 0, 0, 2, tzinfo=timezone.utc),
    ) == 2.0
    assert impact_query_recall({"a", "b"}, {"b", "c"}) == 0.5


def test_baselines_and_ablation_table() -> None:
    corpus = generate_synthetic_corpus(size=4)
    metrics = EvaluationMetrics(stale_surface_rate=0.1, time_to_flag_seconds=0.2, impact_query_recall=1.0)

    warehouse = warehouse_similarity_baseline(corpus.items, limit=2)
    decay = decay_baseline(corpus.items, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    ablated = evaluate_ablation(AblationConfig(dependency_graph=False, currency_filter=False), base=metrics)
    table = render_results_table({"Solomon": metrics, "Ablated": ablated})

    assert len(warehouse) == 2
    assert decay[0][1] >= decay[-1][1]
    assert ablated.impact_query_recall == 0.0
    assert "| Solomon |" in table


def test_currency_evaluation_harness_runs_real_propagation_and_recall() -> None:
    metrics = run_currency_evaluation(size=6)

    assert metrics["Solomon"].stale_surface_rate == 0.0
    assert metrics["Solomon"].time_to_flag_seconds >= 0.0
    assert metrics["Solomon"].time_to_flag_seconds != float("inf")
    assert metrics["Solomon"].impact_query_recall == 1.0
    assert metrics["Warehouse"].stale_surface_rate > 0.0


def test_boundary_fidelity_eval_flags_leaks() -> None:
    result = boundary_fidelity_eval(
        [{"event_id": "safe", "payload": "[CLIENT_1]"}, {"event_id": "leak", "payload": "Client A"}],
        forbidden_terms={"Client A"},
    )

    assert result.ok is False
    assert result.leaked_event_ids == ["leak"]


def test_boundary_fidelity_suite_runs_vendored_boundary_roundtrip() -> None:
    result = run_boundary_fidelity_suite()

    assert result.ok is True
    assert result.total_events >= 3
    assert result.leaked_event_ids == []


def test_recall_weight_calibration_selects_default_profile() -> None:
    calibration = tune_recall_weights()

    assert calibration.selected_weights == RecallWeights(similarity=0.70, credence=0.20, centrality=0.10)
    assert calibration.scores[0].mean_reciprocal_rank == 1.0
    assert any(score.mean_reciprocal_rank < 1.0 for score in calibration.scores[1:])


def test_synthetic_corpus_export_is_reproducible(tmp_path: Path) -> None:
    corpus = generate_synthetic_corpus(size=4)
    exported = export_synthetic_corpus(corpus)
    target = tmp_path / "corpus.json"

    write_synthetic_corpus(str(target), size=4)

    assert exported.schema_id == "solomon.synthetic_corpus.v1"
    assert exported.expected_stale_item_ids == ["item-0", "item-2"]
    assert '"expected_stale_item_ids": [' in target.read_text(encoding="utf-8")


def test_jurisdiction_coverage_benchmark_covers_vendored_packs() -> None:
    cases = generate_jurisdiction_coverage_cases()
    result = run_jurisdiction_coverage_benchmark(cases)

    assert len(cases) == result.total_supported_jurisdictions
    assert result.jurisdiction_coverage_rate == 1.0
    assert result.finding_recall == 1.0
    assert result.missing_jurisdictions == []
    assert result.failed_case_ids == []
    assert "SG" in result.covered_jurisdictions


def test_external_law_monitoring_benchmark_detects_and_propagates_changes() -> None:
    result = run_external_law_monitoring_benchmark(default_external_law_monitor_cases())

    assert result.monitored_authorities == 4
    assert result.expected_changed_authorities == 3
    assert result.change_detection_recall == 1.0
    assert result.false_positive_rate == 0.0
    assert result.impact_query_recall == 1.0
    assert "sg-reg-r-12" in result.detected_changed_authority_ids
    assert "us-reg-fd" not in result.detected_changed_authority_ids
