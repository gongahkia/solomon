# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.boundary.engine.jurisdictions import resolve_pack, supported_jurisdiction_codes
from solomon.boundary.engine.review import review_text
from solomon.boundary.solomon import SolomonBoundary
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


class JurisdictionCoverageCase(SolomonModel):
    case_id: str
    jurisdiction: str
    text: str
    expected_finding_kinds: list[str] = Field(default_factory=lambda: ["jurisdiction_strict_term"])


class JurisdictionCoverageResult(SolomonModel):
    schema_id: str = "solomon.jurisdiction_coverage.v1"
    case_count: int
    total_supported_jurisdictions: int
    covered_jurisdictions: list[str]
    missing_jurisdictions: list[str]
    jurisdiction_coverage_rate: float
    finding_recall: float
    failed_case_ids: list[str] = Field(default_factory=list)


class BoundaryFidelityCase(SolomonModel):
    case_id: str
    input_text: str
    forbidden_terms: list[str]


class ExternalAuthoritySnapshot(SolomonModel):
    authority_id: str
    jurisdiction: str
    source_ref: str
    version: str
    content_sha256: str
    captured_at: datetime


class ExternalLawMonitorCase(SolomonModel):
    case_id: str
    before: ExternalAuthoritySnapshot
    after: ExternalAuthoritySnapshot
    expected_changed: bool


class ExternalLawMonitoringResult(SolomonModel):
    schema_id: str = "solomon.external_law_monitoring.v1"
    monitored_authorities: int
    monitored_jurisdictions: list[str]
    expected_changed_authorities: int
    detected_changed_authority_ids: list[str]
    missed_changed_authority_ids: list[str]
    false_positive_authority_ids: list[str]
    change_detection_recall: float
    false_positive_rate: float
    impact_query_recall: float


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


def generate_jurisdiction_coverage_cases() -> list[JurisdictionCoverageCase]:
    cases: list[JurisdictionCoverageCase] = []
    for code in supported_jurisdiction_codes():
        pack = resolve_pack(code)
        strict_term = pack.strict_terms[0] if pack.strict_terms else pack.name
        cases.append(
            JurisdictionCoverageCase(
                case_id=f"{code.lower()}-strict-term",
                jurisdiction=code,
                text=f"{strict_term} appears in a {pack.name} matter.",
            )
        )
    return cases


def run_jurisdiction_coverage_benchmark(
    cases: list[JurisdictionCoverageCase] | None = None,
) -> JurisdictionCoverageResult:
    resolved_cases = cases or generate_jurisdiction_coverage_cases()
    supported = set(supported_jurisdiction_codes())
    covered: set[str] = set()
    failed_case_ids: list[str] = []
    expected_findings = 0
    matched_findings = 0

    for case in resolved_cases:
        _classification, findings = review_text(
            case.text,
            source_jurisdiction=case.jurisdiction,
            destination_jurisdiction=case.jurisdiction,
        )
        found_kinds = {finding.kind for finding in findings}
        expected_findings += len(case.expected_finding_kinds)
        missing_kinds = [kind for kind in case.expected_finding_kinds if kind not in found_kinds]
        matched_findings += len(case.expected_finding_kinds) - len(missing_kinds)
        if missing_kinds:
            failed_case_ids.append(case.case_id)
        else:
            covered.add(case.jurisdiction.upper())

    covered_supported = supported & covered
    missing_jurisdictions = sorted(supported - covered_supported)
    return JurisdictionCoverageResult(
        case_count=len(resolved_cases),
        total_supported_jurisdictions=len(supported),
        covered_jurisdictions=sorted(covered_supported),
        missing_jurisdictions=missing_jurisdictions,
        jurisdiction_coverage_rate=len(covered_supported) / len(supported) if supported else 1.0,
        finding_recall=matched_findings / expected_findings if expected_findings else 1.0,
        failed_case_ids=failed_case_ids,
    )


def default_external_law_monitor_cases() -> list[ExternalLawMonitorCase]:
    return [
        _monitor_case(
            case_id="sg-reg-r-12",
            authority_id="sg-reg-r-12",
            jurisdiction="SG",
            source_ref="fixture://sg/reg-r-12",
            before_version="2024-01",
            after_version="2025-01",
            before_text="Regulation R section 12 permits structure X with filing A.",
            after_text="Regulation R section 12 requires re-verification before structure X filing A.",
            expected_changed=True,
        ),
        _monitor_case(
            case_id="uk-mar-article-7",
            authority_id="uk-mar-article-7",
            jurisdiction="UK",
            source_ref="fixture://uk/mar/article-7",
            before_version="2024-03",
            after_version="2025-02",
            before_text="UK MAR Article 7 inside information guidance baseline.",
            after_text="UK MAR Article 7 inside information guidance updated for selective disclosure.",
            expected_changed=True,
        ),
        _monitor_case(
            case_id="eu-mar-article-7",
            authority_id="eu-mar-article-7",
            jurisdiction="EU",
            source_ref="fixture://eu/mar/article-7",
            before_version="2024-02",
            after_version="2025-04",
            before_text="EU MAR Article 7 baseline text.",
            after_text="EU MAR Article 7 amended guidance text.",
            expected_changed=True,
        ),
        _monitor_case(
            case_id="us-reg-fd",
            authority_id="us-reg-fd",
            jurisdiction="US",
            source_ref="fixture://us/reg-fd",
            before_version="2024-01",
            after_version="2024-01",
            before_text="Reg FD selective disclosure baseline.",
            after_text="Reg FD selective disclosure baseline.",
            expected_changed=False,
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


def detect_external_authority_change(before: ExternalAuthoritySnapshot, after: ExternalAuthoritySnapshot) -> bool:
    return before.version != after.version or before.content_sha256 != after.content_sha256


def run_external_law_monitoring_benchmark(
    cases: list[ExternalLawMonitorCase] | None = None,
) -> ExternalLawMonitoringResult:
    resolved_cases = cases or default_external_law_monitor_cases()
    expected_changed_authority_ids = {
        case.after.authority_id for case in resolved_cases if case.expected_changed
    }
    detected_authority_ids: set[str] = set()
    false_positive_authority_ids: set[str] = set()
    unchanged_expected = 0

    for case in resolved_cases:
        changed = detect_external_authority_change(case.before, case.after)
        if changed:
            detected_authority_ids.add(case.after.authority_id)
        if not case.expected_changed:
            unchanged_expected += 1
        if changed and not case.expected_changed:
            false_positive_authority_ids.add(case.after.authority_id)

    missed_authority_ids = expected_changed_authority_ids - detected_authority_ids
    return ExternalLawMonitoringResult(
        monitored_authorities=len(resolved_cases),
        monitored_jurisdictions=sorted({case.after.jurisdiction for case in resolved_cases}),
        expected_changed_authorities=len(expected_changed_authority_ids),
        detected_changed_authority_ids=sorted(detected_authority_ids),
        missed_changed_authority_ids=sorted(missed_authority_ids),
        false_positive_authority_ids=sorted(false_positive_authority_ids),
        change_detection_recall=impact_query_recall(expected_changed_authority_ids, detected_authority_ids),
        false_positive_rate=len(false_positive_authority_ids) / unchanged_expected if unchanged_expected else 0.0,
        impact_query_recall=_monitoring_impact_query_recall(resolved_cases, detected_authority_ids),
    )


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
    boundary: SolomonBoundary | None = None,
    cases: list[BoundaryFidelityCase] | None = None,
) -> BoundaryFidelityResult:
    resolved_boundary = boundary or SolomonBoundary()
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
    coverage = run_jurisdiction_coverage_benchmark()
    monitoring = run_external_law_monitoring_benchmark()
    print(
        json.dumps(
            {
                "table": render_results_table(metrics),
                "jurisdiction_coverage": coverage.model_dump(mode="json"),
                "external_law_monitoring": monitoring.model_dump(mode="json"),
            },
            indent=2,
        )
    )
    return 0


def _monitor_case(
    *,
    case_id: str,
    authority_id: str,
    jurisdiction: str,
    source_ref: str,
    before_version: str,
    after_version: str,
    before_text: str,
    after_text: str,
    expected_changed: bool,
) -> ExternalLawMonitorCase:
    before_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    after_time = datetime(2025, 6, 1, tzinfo=timezone.utc)
    return ExternalLawMonitorCase(
        case_id=case_id,
        before=ExternalAuthoritySnapshot(
            authority_id=authority_id,
            jurisdiction=jurisdiction,
            source_ref=source_ref,
            version=before_version,
            content_sha256=_content_hash(before_text),
            captured_at=before_time,
        ),
        after=ExternalAuthoritySnapshot(
            authority_id=authority_id,
            jurisdiction=jurisdiction,
            source_ref=source_ref,
            version=after_version,
            content_sha256=_content_hash(after_text),
            captured_at=after_time,
        ),
        expected_changed=expected_changed,
    )


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _monitoring_impact_query_recall(
    cases: list[ExternalLawMonitorCase],
    detected_authority_ids: set[str],
) -> float:
    expected_item_ids = {f"monitor-item-{case.case_id}" for case in cases if case.expected_changed}
    if not expected_item_ids:
        return 1.0

    with tempfile.TemporaryDirectory(prefix="solomon-monitor-eval-") as tmp:
        db = Path(tmp) / "solomon.sqlite3"
        store = SQLiteKnowledgeStore(db)
        graph = GraphStore(db)
        for case in cases:
            item_id = f"monitor-item-{case.case_id}"
            item = KnowledgeItem(
                id=item_id,
                kind=KnowledgeKind.POSITION,
                content=f"{case.after.jurisdiction} position depending on {case.after.authority_id}",
                provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref=f"monitor-{case.case_id}"),
                valid_from=case.before.captured_at - timedelta(days=30),
                ingested_at=case.before.captured_at - timedelta(days=30),
                last_verified_at=case.before.captured_at,
                credence_tier=CredenceTier.FIRM_AUTHORITATIVE,
                metadata={
                    "authority_id": case.after.authority_id,
                    "jurisdiction": case.after.jurisdiction,
                    "source_ref": case.after.source_ref,
                },
            )
            store.write_item(item)
            graph.add_dependency(
                DependencyEdge(
                    id=f"monitor-edge-{case.case_id}",
                    source_id=item_id,
                    target_id=case.after.authority_id,
                    edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
                    target_kind="external_authority",
                    valid_from=case.before.captured_at - timedelta(days=30),
                    created_at=case.before.captured_at - timedelta(days=30),
                )
            )

        actual_item_ids: set[str] = set()
        propagator = CurrencyPropagator(graph=graph, store=store)
        for authority_id in detected_authority_ids:
            impact = propagator.propagate_dependency_change(
                authority_id,
                changed_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
                reason=f"{authority_id} changed in external-law monitor fixture",
            )
            actual_item_ids.update(impact.stale_item_ids)

    return impact_query_recall(expected_item_ids, actual_item_ids)


if __name__ == "__main__":
    raise SystemExit(main())
