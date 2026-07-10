# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime
from enum import Enum
from itertools import combinations
from typing import Any

from pydantic import Field, field_validator

from solomon.api.schemas import SolomonModel
from solomon.currency.models import CurrencyState, KnowledgeItem, KnowledgeKind, VerifiedState, now_utc
from solomon.graph.models import DependencyEdge, EdgeType
from solomon.graph.types import DependencyGraphProtocol
from solomon.store.types import KnowledgeStoreProtocol


class ConclusionPolarity(str, Enum):
    AFFIRMATIVE = "affirmative"
    NEGATIVE = "negative"


class ContradictionSignal(SolomonModel):
    signal_id: str
    item_id: str
    conflicting_item_id: str
    authority_id: str
    kind: str = "same_authority_opposite_conclusion"
    item_polarity: ConclusionPolarity
    conflicting_polarity: ConclusionPolarity
    conclusion: str | None = None
    conflicting_conclusion: str | None = None
    detected_at: datetime = Field(default_factory=now_utc)
    basis: str
    requires_human_review: bool = True

    @field_validator("detected_at")
    @classmethod
    def normalize_detected_at(cls, value: datetime) -> datetime:
        from solomon.currency.models import _ensure_aware_utc

        return _ensure_aware_utc(value)


def conclusion_polarity(item: KnowledgeItem) -> ConclusionPolarity | None:
    raw = item.metadata.get("conclusion_polarity")
    if raw is None:
        return None
    try:
        return ConclusionPolarity(str(raw))
    except ValueError:
        return None


def contradictions_for_item(item: KnowledgeItem) -> list[ContradictionSignal]:
    values = item.metadata.get("contradictions", [])
    if not isinstance(values, list):
        return []
    return [ContradictionSignal.model_validate(value) for value in values]


def append_contradiction_signal(item: KnowledgeItem, signal: ContradictionSignal) -> KnowledgeItem:
    existing = contradictions_for_item(item)
    if any(entry.signal_id == signal.signal_id for entry in existing):
        return item
    contradictions = [entry.model_dump(mode="json") for entry in existing]
    contradictions.append(signal.model_dump(mode="json"))
    staleness_reasons = list(item.metadata.get("staleness_reasons", []))
    staleness_reasons.append(
        {
            "dependency_id": signal.authority_id,
            "changed_at": signal.detected_at.isoformat(),
            "reason": signal.basis,
            "edge_id": signal.signal_id,
        }
    )
    return item.model_copy(
        update={
            "currency_state": CurrencyState.STALE_PENDING_REVERIFICATION,
            "verified_state": VerifiedState.NEEDS_REVIEW,
            "metadata": {
                **item.metadata,
                "contradictions": contradictions,
                "contradiction_status": "open",
                "staleness_reasons": staleness_reasons,
            },
        }
    )


def detect_same_authority_opposite_conclusions(
    *,
    store: KnowledgeStoreProtocol,
    graph: DependencyGraphProtocol,
    matter_id: str | None = None,
    client_id: str | None = None,
    detected_at: datetime | None = None,
) -> list[ContradictionSignal]:
    timestamp = detected_at or now_utc()
    live_positions = [
        item
        for item in store.get_many(include_states={CurrencyState.LIVE}, matter_id=matter_id, client_id=client_id)
        if item.kind is KnowledgeKind.POSITION and conclusion_polarity(item) is not None
    ]
    by_authority: dict[str, list[KnowledgeItem]] = defaultdict(list)
    for item in live_positions:
        for edge in _external_dependencies(graph.get_dependencies(item.id)):
            by_authority[edge.target_id].append(item)

    signals: list[ContradictionSignal] = []
    for authority_id, items in sorted(by_authority.items()):
        for left, right in combinations(sorted(items, key=lambda item: item.id), 2):
            left_polarity = conclusion_polarity(left)
            right_polarity = conclusion_polarity(right)
            if left_polarity is None or right_polarity is None:
                continue
            if _is_successor_pair(left, right) or not _opposes(left_polarity, right_polarity):
                continue
            signals.append(_signal(left, right, authority_id, timestamp))
            signals.append(_signal(right, left, authority_id, timestamp))
    return signals


def _external_dependencies(edges: list[DependencyEdge]) -> list[DependencyEdge]:
    return [
        edge
        for edge in edges
        if edge.edge_type is EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL and edge.target_kind == "external_authority"
    ]


def _opposes(left: ConclusionPolarity, right: ConclusionPolarity) -> bool:
    return (left is ConclusionPolarity.AFFIRMATIVE and right is ConclusionPolarity.NEGATIVE) or (
        left is ConclusionPolarity.NEGATIVE and right is ConclusionPolarity.AFFIRMATIVE
    )


def _is_successor_pair(left: KnowledgeItem, right: KnowledgeItem) -> bool:
    return (
        left.successor_id == right.id
        or right.successor_id == left.id
        or left.metadata.get("supersedes") == right.id
        or right.metadata.get("supersedes") == left.id
    )


def _signal(left: KnowledgeItem, right: KnowledgeItem, authority_id: str, detected_at: datetime) -> ContradictionSignal:
    left_polarity = conclusion_polarity(left)
    right_polarity = conclusion_polarity(right)
    if left_polarity is None or right_polarity is None:
        raise ValueError("contradiction signals require conclusion polarity")
    return ContradictionSignal(
        signal_id=_signal_id(left.id, right.id, authority_id),
        item_id=left.id,
        conflicting_item_id=right.id,
        authority_id=authority_id,
        item_polarity=left_polarity,
        conflicting_polarity=right_polarity,
        conclusion=_metadata_text(left.metadata, "conclusion"),
        conflicting_conclusion=_metadata_text(right.metadata, "conclusion"),
        detected_at=detected_at,
        basis=f"live positions cite {authority_id} with opposite conclusion polarity",
    )


def _metadata_text(metadata: dict[str, Any], key: str) -> str | None:
    value = str(metadata.get(key) or "").strip()
    return value or None


def _signal_id(item_id: str, conflicting_item_id: str, authority_id: str) -> str:
    digest = hashlib.sha256(f"{item_id}|{conflicting_item_id}|{authority_id}".encode()).hexdigest()[:24]
    return f"contradiction:{digest}"
