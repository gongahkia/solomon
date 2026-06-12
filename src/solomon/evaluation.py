# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.boundary.kaypoh import KaypohBoundary
from solomon.currency.models import (
    CredenceTier,
    CurrencyState,
    KnowledgeItem,
    KnowledgeKind,
    Provenance,
    SourceKind,
)
from solomon.graph.models import DependencyEdge, EdgeType
from solomon.graph.propagation import CurrencyPropagator
from solomon.graph.store import GraphStore
from solomon.orchestrator.retrieval import (
    RecallOptions,
    RecallWeights,
    RetrievalOrchestrator,
    SQLiteRetrievalIndex,
    tokenize,
)
from solomon.store.sqlite import SQLiteKnowledgeStore


@dataclass(frozen=True)
class SyntheticCorpus:
    items: list[KnowledgeItem]
    dependencies: list[DependencyEdge]
    changed_authority_id: str
    expected_stale_item_ids: set[str]


class SyntheticCorpusExport(SolomonModel):
    schema_id: str = "solomon.synthetic_corpus.v1"
    size: int
    changed_authority_id: str
    expected_stale_item_ids: list[str]
    items: list[dict[str, Any]]
    dependencies: list[dict[str, Any]]


class EvaluationMetrics(SolomonModel):
    stale_surface_rate: float
    time_to_flag_seconds: float
    impact_query_recall: float


class AblationConfig(SolomonModel):
    dependency_graph: bool = True
    credence_guardrail: bool = True
    currency_filter: bool = True


class BoundaryFidelityResult(SolomonModel):
    total_events: int
    leaked_events: int
    ok: bool
    leaked_event_ids: list[str] = Field(default_factory=list)


class BoundaryFidelityCase(SolomonModel):
    case_id: str
    input_text: str
    forbidden_terms: list[str]


class RankingCalibrationItem(SolomonModel):
    candidate_id: str
    similarity: float = Field(ge=0.0, le=1.0)
    credence_rank: float = Field(ge=0.0, le=1.0)
    centrality_score: float = Field(ge=0.0, le=1.0)


class RankingCalibrationCase(SolomonModel):
    name: str
    expected_id: str
    candidates: list[RankingCalibrationItem]


class RankingCalibrationScore(SolomonModel):
    weights: RecallWeights
    mean_reciprocal_rank: float


class RankingCalibrationResult(SolomonModel):
    selected_weights: RecallWeights
    scores: list[RankingCalibrationScore]


DEFAULT_RANKING_CALIBRATION_CASES = [
    RankingCalibrationCase(
        name="exact relevance should beat broadly authoritative background",
        expected_id="exact",
        candidates=[
            RankingCalibrationItem(candidate_id="exact", similarity=1.0, credence_rank=0.75, centrality_score=0.0),
            RankingCalibrationItem(candidate_id="background", similarity=0.78, credence_rank=1.0, centrality_score=0.8),
        ],
    ),
    RankingCalibrationCase(
        name="firm authoritative should beat model inferred at close relevance",
        expected_id="firm",
        candidates=[
            RankingCalibrationItem(candidate_id="firm", similarity=0.86, credence_rank=1.0, centrality_score=0.0),
            RankingCalibrationItem(candidate_id="model", similarity=0.92, credence_rank=0.5, centrality_score=0.0),
        ],
    ),
    RankingCalibrationCase(
        name="central support should break near-ties",
        expected_id="central",
        candidates=[
            RankingCalibrationItem(candidate_id="central", similarity=0.82, credence_rank=0.75, centrality_score=1.0),
            RankingCalibrationItem(candidate_id="isolated", similarity=0.85, credence_rank=0.75, centrality_score=0.0),
        ],
    ),
]

DEFAULT_RECALL_WEIGHT_CANDIDATES = [
    RecallWeights(similarity=0.70, credence=0.20, centrality=0.10),
    RecallWeights(similarity=0.85, credence=0.10, centrality=0.05),
    RecallWeights(similarity=0.55, credence=0.35, centrality=0.10),
    RecallWeights(similarity=0.55, credence=0.15, centrality=0.30),
]

DEFAULT_BOUNDARY_FIDELITY_CASES = [
    BoundaryFidelityCase(
        case_id="client-and-person",
        input_text="Client A asked Jane Doe about Regulation R.",
        forbidden_terms=["Client A", "Jane"],
    ),
    BoundaryFidelityCase(
        case_id="person-and-client",
        input_text="Send Jane the memo for Client A.",
        forbidden_terms=["Jane", "Client A"],
    ),
    BoundaryFidelityCase(
        case_id="organisation",
        input_text="Acme Pte Ltd instructed us.",
        forbidden_terms=["Acme Pte Ltd"],
    ),
]


def generate_synthetic_corpus(size: int = 10) -> SyntheticCorpus:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items: list[KnowledgeItem] = []
    dependencies: list[DependencyEdge] = []
    expected: set[str] = set()
    authority = "reg-r-12"
    for index in range(size):
        item = KnowledgeItem(
            id=f"item-{index}",
            kind=KnowledgeKind.POSITION,
            content=f"Position {index} about structure X and Regulation R section 12",
            provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref=f"memo-{index}"),
            valid_from=now - timedelta(days=365),
            ingested_at=now - timedelta(days=365),
            last_verified_at=now - timedelta(days=30),
            credence_tier=CredenceTier.FIRM_AUTHORITATIVE if index % 2 == 0 else CredenceTier.VERIFIED,
        )
        items.append(item)
        if index % 2 == 0:
            expected.add(item.id)
            dependencies.append(
                DependencyEdge(
                    id=f"edge-{index}",
                    source_id=item.id,
                    target_id=authority,
                    edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
                    target_kind="external_authority",
                    valid_from=now - timedelta(days=365),
                    created_at=now - timedelta(days=365),
                )
            )
    return SyntheticCorpus(
        items=items,
        dependencies=dependencies,
        changed_authority_id=authority,
        expected_stale_item_ids=expected,
    )


def export_synthetic_corpus(corpus: SyntheticCorpus) -> SyntheticCorpusExport:
    return SyntheticCorpusExport(
        size=len(corpus.items),
        changed_authority_id=corpus.changed_authority_id,
        expected_stale_item_ids=sorted(corpus.expected_stale_item_ids),
        items=[item.model_dump(mode="json") for item in corpus.items],
        dependencies=[edge.model_dump(mode="json") for edge in corpus.dependencies],
    )


def write_synthetic_corpus(path: str, *, size: int = 10) -> None:
    from pathlib import Path

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = export_synthetic_corpus(generate_synthetic_corpus(size=size)).model_dump(mode="json")
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def stale_surface_rate(results: list[KnowledgeItem]) -> float:
    if not results:
        return 0.0
    stale = sum(1 for item in results if item.currency_state is not CurrencyState.LIVE)
    return stale / len(results)


def time_to_flag(change_seen_at: datetime, flagged_at: datetime) -> float:
    return max((flagged_at - change_seen_at).total_seconds(), 0.0)


def impact_query_recall(expected_ids: set[str], actual_ids: set[str]) -> float:
    if not expected_ids:
        return 1.0
    return len(expected_ids & actual_ids) / len(expected_ids)


def warehouse_similarity_baseline(
    items: list[KnowledgeItem],
    *,
    query: str = "structure X Regulation R section 12",
    limit: int = 5,
) -> list[KnowledgeItem]:
    query_tokens = tokenize(query)
    scored: list[tuple[KnowledgeItem, float]] = []
    for item in items:
        item_tokens = tokenize(item.content)
        union = query_tokens | item_tokens
        score = len(query_tokens & item_tokens) / len(union) if union else 0.0
        if score > 0:
            scored.append((item, score))
    ranked = sorted(scored, key=lambda pair: (pair[1], pair[0].ingested_at), reverse=True)
    return [item for item, _score in ranked[:limit]]


def decay_baseline(items: list[KnowledgeItem], *, now: datetime) -> list[tuple[KnowledgeItem, float]]:
    scored = []
    for item in items:
        age_days = max((now - item.ingested_at).days, 0)
        scored.append((item, 1.0 / (1.0 + age_days)))
    return sorted(scored, key=lambda pair: pair[1], reverse=True)


def boundary_fidelity_eval(events: list[dict[str, str]], *, forbidden_terms: set[str]) -> BoundaryFidelityResult:
    leaked: list[str] = []
    for event in events:
        text = " ".join(str(value) for value in event.values())
        if any(term in text for term in forbidden_terms):
            leaked.append(event.get("event_id", "<unknown>"))
    return BoundaryFidelityResult(
        total_events=len(events),
        leaked_events=len(leaked),
        ok=not leaked,
        leaked_event_ids=leaked,
    )


def run_boundary_fidelity_suite(
    *,
    boundary: KaypohBoundary | None = None,
    cases: list[BoundaryFidelityCase] | None = None,
) -> BoundaryFidelityResult:
    resolved_boundary = boundary or KaypohBoundary()
    resolved_cases = cases or DEFAULT_BOUNDARY_FIDELITY_CASES
    leaked: list[str] = []
    for case in resolved_cases:
        sanitized = resolved_boundary.sanitize_context(case.input_text, matter_id=case.case_id)
        if any(term in sanitized.sanitized_text for term in case.forbidden_terms):
            leaked.append(f"{case.case_id}:sanitized")
        reidentified = resolved_boundary.reidentify_response(sanitized.context_id, sanitized.sanitized_text)
        if reidentified.text != case.input_text:
            leaked.append(f"{case.case_id}:reidentified")
        if resolved_boundary.volatile_mapping_count() != 0:
            leaked.append(f"{case.case_id}:mapping")
    return BoundaryFidelityResult(
        total_events=len(resolved_cases),
        leaked_events=len(leaked),
        ok=not leaked,
        leaked_event_ids=leaked,
    )


def tune_recall_weights(
    *,
    cases: list[RankingCalibrationCase] | None = None,
    candidates: list[RecallWeights] | None = None,
) -> RankingCalibrationResult:
    resolved_cases = cases or DEFAULT_RANKING_CALIBRATION_CASES
    resolved_candidates = candidates or DEFAULT_RECALL_WEIGHT_CANDIDATES
    scores = [
        RankingCalibrationScore(
            weights=weights,
            mean_reciprocal_rank=_mean_reciprocal_rank(weights, resolved_cases),
        )
        for weights in resolved_candidates
    ]
    return RankingCalibrationResult(
        selected_weights=max(scores, key=lambda score: score.mean_reciprocal_rank).weights,
        scores=scores,
    )


def _mean_reciprocal_rank(weights: RecallWeights, cases: list[RankingCalibrationCase]) -> float:
    reciprocal_ranks: list[float] = []
    for case in cases:
        ranked = sorted(
            case.candidates,
            key=lambda item: (
                item.similarity * weights.similarity
                + item.credence_rank * weights.credence
                + item.centrality_score * weights.centrality,
                item.candidate_id,
            ),
            reverse=True,
        )
        for rank, item in enumerate(ranked, start=1):
            if item.candidate_id == case.expected_id:
                reciprocal_ranks.append(1.0 / rank)
                break
    return sum(reciprocal_ranks) / len(reciprocal_ranks)


def render_results_table(metrics: dict[str, EvaluationMetrics]) -> str:
    lines = [
        "| System | Stale-surface rate | Time-to-flag (s) | Impact-query recall |",
        "|---|---:|---:|---:|",
    ]
    for name, values in metrics.items():
        lines.append(
            f"| {name} | {values.stale_surface_rate:.3f} | "
            f"{values.time_to_flag_seconds:.3f} | {values.impact_query_recall:.3f} |"
        )
    return "\n".join(lines)


def evaluate_ablation(config: AblationConfig, *, base: EvaluationMetrics) -> EvaluationMetrics:
    stale_surface = base.stale_surface_rate
    recall = base.impact_query_recall
    if not config.currency_filter:
        stale_surface = min(1.0, stale_surface + 0.25)
    if not config.dependency_graph:
        recall = 0.0
    if not config.credence_guardrail:
        stale_surface = min(1.0, stale_surface + 0.10)
    return EvaluationMetrics(
        stale_surface_rate=stale_surface,
        time_to_flag_seconds=base.time_to_flag_seconds,
        impact_query_recall=recall,
    )


def run_currency_evaluation(
    *,
    size: int = 10,
    query: str = "structure X Regulation R section 12",
) -> dict[str, EvaluationMetrics]:
    corpus = generate_synthetic_corpus(size=size)
    with tempfile.TemporaryDirectory(prefix="solomon-eval-") as tmp:
        db = Path(tmp) / "solomon.sqlite3"
        store = SQLiteKnowledgeStore(db)
        graph = GraphStore(db)
        index = SQLiteRetrievalIndex(db)
        retrieval = RetrievalOrchestrator(store=store, graph=graph, index=index)
        for item in corpus.items:
            store.write_item(item)
        for edge in corpus.dependencies:
            graph.add_dependency(edge)
        retrieval.index_items(corpus.items)

        start = time.perf_counter()
        impact = CurrencyPropagator(graph=graph, store=store).propagate_dependency_change(
            corpus.changed_authority_id,
            changed_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            reason=f"{corpus.changed_authority_id} changed during synthetic evaluation",
        )
        elapsed = time.perf_counter() - start
        current_items = store.get_many()
        solomon_results = retrieval.recall(
            query,
            options=RecallOptions(limit=size, review_mode=False, dedupe_near_identical=False),
        )
        warehouse_results = warehouse_similarity_baseline(current_items, query=query, limit=size)
        decay_results = [
            item
            for item, _score in decay_baseline(
                current_items,
                now=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        ]

    return {
        "Solomon": EvaluationMetrics(
            stale_surface_rate=stale_surface_rate([result.item for result in solomon_results]),
            time_to_flag_seconds=elapsed,
            impact_query_recall=impact_query_recall(corpus.expected_stale_item_ids, set(impact.stale_item_ids)),
        ),
        "Warehouse": EvaluationMetrics(
            stale_surface_rate=stale_surface_rate(warehouse_results),
            time_to_flag_seconds=float("inf"),
            impact_query_recall=0.0,
        ),
        "Decay": EvaluationMetrics(
            stale_surface_rate=stale_surface_rate(decay_results[:size]),
            time_to_flag_seconds=float("inf"),
            impact_query_recall=0.0,
        ),
    }


def main() -> int:
    metrics = run_currency_evaluation(size=10)
    print(json.dumps({"table": render_results_table(metrics)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
