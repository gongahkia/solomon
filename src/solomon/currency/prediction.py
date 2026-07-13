# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import csv
import json
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from solomon.api.schemas import SolomonModel
from solomon.currency.models import _ensure_aware_utc, now_utc
from solomon.graph.models import DependencyEdge, EdgeConfidence
from solomon.graph.types import DependencyGraphProtocol
from solomon.store.sqlite import ItemNotFoundError
from solomon.store.types import KnowledgeStoreProtocol


class PendingAuthorityAmendment(SolomonModel):
    authority_id: str
    expected_change_at: datetime
    description: str
    source_ref: str | None = None
    status: Literal["pending", "consultation", "enacted-not-effective"] = "pending"

    @field_validator("expected_change_at")
    @classmethod
    def normalize_expected_change_at(cls, value: datetime) -> datetime:
        return _ensure_aware_utc(value)


class StalenessRisk(SolomonModel):
    item_id: str
    authority_id: str
    expected_change_at: datetime
    risk_level: Literal["low", "medium", "high"]
    forecast_score: float = Field(ge=0.0, le=1.0)
    historical_change_count: int = 0
    reason: str
    dependency_path: list[str] = Field(default_factory=list)


class AuthorityChangeHistory(SolomonModel):
    authority_id: str
    changed_at: datetime
    source_ref: str | None = None

    @field_validator("changed_at")
    @classmethod
    def normalize_changed_at(cls, value: datetime) -> datetime:
        return _ensure_aware_utc(value)


class StalenessRiskReport(SolomonModel):
    generated_at: datetime
    lookahead_days: int
    risks: list[StalenessRisk]


def load_pending_amendments(path: Path | str) -> list[PendingAuthorityAmendment]:
    source = Path(path)
    if source.suffix.lower() == ".json":
        raw = json.loads(source.read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else raw.get("pending_amendments", [])
    elif source.suffix.lower() == ".csv":
        with source.open("r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
    else:
        raise ValueError("pending amendment feed must be .json or .csv")
    return [PendingAuthorityAmendment.model_validate(row) for row in rows]


def predict_staleness_risk(
    amendments: list[PendingAuthorityAmendment],
    *,
    graph: DependencyGraphProtocol,
    store: KnowledgeStoreProtocol,
    history: list[AuthorityChangeHistory] | None = None,
    as_of: datetime | None = None,
    lookahead_days: int = 180,
) -> StalenessRiskReport:
    timestamp = as_of or now_utc()
    horizon = timestamp + timedelta(days=lookahead_days)
    risks: dict[tuple[str, str], StalenessRisk] = {}
    history_by_authority = _history_by_authority(history or [], as_of=timestamp)

    for amendment in amendments:
        if amendment.expected_change_at < timestamp or amendment.expected_change_at > horizon:
            continue
        centrality = graph.centrality([amendment.authority_id]).get(amendment.authority_id, 0)
        for item_id, path_edges in _transitive_dependents(graph, amendment.authority_id):
            try:
                store.get_item(item_id)
            except ItemNotFoundError:
                continue
            edge_confidences = [edge.confidence for edge in path_edges]
            historical_change_count = len(history_by_authority.get(amendment.authority_id, []))
            forecast_score = _forecast_score(
                amendment=amendment,
                as_of=timestamp,
                centrality=centrality,
                edge_confidences=edge_confidences,
                historical_change_count=historical_change_count,
            )
            key = (item_id, amendment.authority_id)
            risk = StalenessRisk(
                item_id=item_id,
                authority_id=amendment.authority_id,
                expected_change_at=amendment.expected_change_at,
                risk_level=_risk_level(forecast_score),
                forecast_score=forecast_score,
                historical_change_count=historical_change_count,
                reason=_risk_reason(amendment, centrality=centrality, historical_change_count=historical_change_count),
                dependency_path=[edge.id for edge in path_edges],
            )
            existing = risks.get(key)
            if existing is None or _risk_rank(risk.risk_level) > _risk_rank(existing.risk_level):
                risks[key] = risk

    return StalenessRiskReport(
        generated_at=timestamp,
        lookahead_days=lookahead_days,
        risks=sorted(
            risks.values(),
            key=lambda risk: (_risk_rank(risk.risk_level), risk.expected_change_at),
            reverse=True,
        ),
    )


def _transitive_dependents(
    graph: DependencyGraphProtocol,
    authority_id: str,
) -> list[tuple[str, list[DependencyEdge]]]:
    queue: deque[tuple[str, list[DependencyEdge]]] = deque(
        (edge.source_id, [edge]) for edge in graph.get_dependents(authority_id)
    )
    visited: set[str] = set()
    dependents: list[tuple[str, list[DependencyEdge]]] = []
    while queue:
        item_id, path = queue.popleft()
        if item_id in visited:
            continue
        visited.add(item_id)
        dependents.append((item_id, path))
        for edge in graph.get_dependents(item_id):
            queue.append((edge.source_id, [*path, edge]))
    return dependents


def _forecast_score(
    *,
    amendment: PendingAuthorityAmendment,
    as_of: datetime,
    centrality: int,
    edge_confidences: list[EdgeConfidence],
    historical_change_count: int,
) -> float:
    expected_change_at = amendment.expected_change_at
    days_until_change = (expected_change_at - as_of).days
    urgency = 1.0 if days_until_change <= 30 else 0.7 if days_until_change <= 90 else 0.4
    graph_weight = min(centrality / 5.0, 1.0)
    status_weight = {
        "enacted-not-effective": 1.0,
        "pending": 0.7,
        "consultation": 0.5,
    }[amendment.status]
    confidence_weight = 0.4 if EdgeConfidence.LLM_SUGGESTED in edge_confidences else 0.8
    history_weight = min(historical_change_count / 3.0, 1.0)
    return min(
        1.0,
        urgency * 0.55 + graph_weight * 0.15 + status_weight * 0.15 + confidence_weight * 0.10 + history_weight * 0.05,
    )


def _risk_level(score: float) -> Literal["low", "medium", "high"]:
    if score >= 0.75:
        return "high"
    if score >= 0.50:
        return "medium"
    return "low"


def _risk_reason(amendment: PendingAuthorityAmendment, *, centrality: int, historical_change_count: int) -> str:
    source = f" ({amendment.source_ref})" if amendment.source_ref else ""
    return (
        f"{amendment.authority_id} has {amendment.status} amendment due "
        f"{amendment.expected_change_at.date().isoformat()}: {amendment.description}{source}; "
        f"{centrality} direct current dependents; {historical_change_count} prior changes in forecast window history"
    )


def _risk_rank(level: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}[level]


def _history_by_authority(
    history: list[AuthorityChangeHistory],
    *,
    as_of: datetime,
    window_days: int = 730,
) -> dict[str, list[AuthorityChangeHistory]]:
    cutoff = as_of - timedelta(days=window_days)
    grouped: dict[str, list[AuthorityChangeHistory]] = {}
    for change in history:
        if cutoff <= change.changed_at <= as_of:
            grouped.setdefault(change.authority_id, []).append(change)
    return grouped
