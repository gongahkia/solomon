# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone

from solomon.currency.models import CurrencyState
from solomon.evaluation import (
    AblationConfig,
    EvaluationMetrics,
    boundary_fidelity_eval,
    decay_baseline,
    evaluate_ablation,
    generate_synthetic_corpus,
    impact_query_recall,
    render_results_table,
    stale_surface_rate,
    time_to_flag,
    warehouse_similarity_baseline,
)


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


def test_boundary_fidelity_eval_flags_leaks() -> None:
    result = boundary_fidelity_eval(
        [{"event_id": "safe", "payload": "[CLIENT_1]"}, {"event_id": "leak", "payload": "Client A"}],
        forbidden_terms={"Client A"},
    )

    assert result.ok is False
    assert result.leaked_event_ids == ["leak"]

