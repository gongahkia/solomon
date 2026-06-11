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
from solomon.graph.store import GraphStore
from solomon.store.sqlite import ItemNotFoundError, SQLiteKnowledgeStore


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
    reason: str
    dependency_path: list[str] = Field(default_factory=list)


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
    graph: GraphStore,
    store: SQLiteKnowledgeStore,
    as_of: datetime | None = None,
    lookahead_days: int = 180,
) -> StalenessRiskReport:
    timestamp = as_of or now_utc()
    horizon = timestamp + timedelta(days=lookahead_days)
    risks: dict[tuple[str, str], StalenessRisk] = {}

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
            key = (item_id, amendment.authority_id)
            risk = StalenessRisk(
                item_id=item_id,
                authority_id=amendment.authority_id,
                expected_change_at=amendment.expected_change_at,
                risk_level=_risk_level(
                    expected_change_at=amendment.expected_change_at,
                    as_of=timestamp,
                    centrality=centrality,
                    edge_confidences=edge_confidences,
                ),
                reason=_risk_reason(amendment, centrality=centrality),
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


def _transitive_dependents(graph: GraphStore, authority_id: str) -> list[tuple[str, list[DependencyEdge]]]:
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


def _risk_level(
    *,
    expected_change_at: datetime,
    as_of: datetime,
    centrality: int,
    edge_confidences: list[EdgeConfidence],
) -> Literal["low", "medium", "high"]:
    days_until_change = (expected_change_at - as_of).days
    if days_until_change <= 30 or centrality >= 5:
        return "high"
    if days_until_change <= 90 or centrality >= 2:
        return "medium"
    if EdgeConfidence.LLM_SUGGESTED in edge_confidences:
        return "low"
    return "medium"


def _risk_reason(amendment: PendingAuthorityAmendment, *, centrality: int) -> str:
    source = f" ({amendment.source_ref})" if amendment.source_ref else ""
    return (
        f"{amendment.authority_id} has {amendment.status} amendment due "
        f"{amendment.expected_change_at.date().isoformat()}: {amendment.description}{source}; "
        f"{centrality} direct current dependents"
    )


def _risk_rank(level: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}[level]
