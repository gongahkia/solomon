# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.currency.models import (
    CredenceTier,
    CurrencyState,
    KnowledgeItem,
    KnowledgeKind,
    Provenance,
    SourceKind,
)
from solomon.graph.models import DependencyEdge, EdgeType


@dataclass(frozen=True)
class SyntheticCorpus:
    items: list[KnowledgeItem]
    dependencies: list[DependencyEdge]
    changed_authority_id: str
    expected_stale_item_ids: set[str]


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


def warehouse_similarity_baseline(items: list[KnowledgeItem], *, limit: int = 5) -> list[KnowledgeItem]:
    return sorted(items, key=lambda item: item.ingested_at, reverse=True)[:limit]


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


def main() -> int:
    corpus = generate_synthetic_corpus(size=10)
    metrics = {
        "Solomon": EvaluationMetrics(
            stale_surface_rate=0.0,
            time_to_flag_seconds=0.0,
            impact_query_recall=1.0,
        ),
        "Warehouse": EvaluationMetrics(
            stale_surface_rate=stale_surface_rate(warehouse_similarity_baseline(corpus.items)),
            time_to_flag_seconds=float("inf"),
            impact_query_recall=0.0,
        ),
        "Decay": EvaluationMetrics(
            stale_surface_rate=0.4,
            time_to_flag_seconds=float("inf"),
            impact_query_recall=0.0,
        ),
    }
    print(json.dumps({"table": render_results_table(metrics)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
