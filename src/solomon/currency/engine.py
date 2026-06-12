# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Literal

from pydantic import Field, field_validator

from solomon.api.schemas import SolomonModel
from solomon.currency.models import CurrencyState, KnowledgeItem, KnowledgeKind, VerifiedState, now_utc
from solomon.graph.models import ImpactResult
from solomon.graph.propagation import CurrencyPropagator
from solomon.graph.store import GraphStore
from solomon.store.sqlite import SQLiteKnowledgeStore


class VerificationOutcome(str, Enum):
    REAFFIRM = "reaffirm"
    SUPERSEDE = "supersede"
    RETIRE = "retire"


class VerificationPolicy(SolomonModel):
    default_max_age_days: int = 365
    high_stakes_max_age_days: int = 180
    high_stakes_kinds: set[KnowledgeKind] = Field(
        default_factory=lambda: {KnowledgeKind.ADVICE, KnowledgeKind.HOUSE_VIEW, KnowledgeKind.POSITION}
    )

    def max_age_for(self, item: KnowledgeItem) -> timedelta:
        days = self.high_stakes_max_age_days if item.kind in self.high_stakes_kinds else self.default_max_age_days
        return timedelta(days=days)


class CurrencyEvaluation(SolomonModel):
    item_id: str
    currency_state: CurrencyState
    explanation: list[str]
    verification_due: bool
    stale_reasons: list[dict[str, object]] = Field(default_factory=list)


class RecordedVerification(SolomonModel):
    item: KnowledgeItem
    outcome: VerificationOutcome
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def normalize_recorded_at(cls, value: datetime) -> datetime:
        from solomon.currency.models import _ensure_aware_utc

        return _ensure_aware_utc(value)


def verification_due(
    item: KnowledgeItem,
    *,
    as_of: datetime | None = None,
    policy: VerificationPolicy | None = None,
) -> bool:
    timestamp = as_of or now_utc()
    resolved_policy = policy or VerificationPolicy()
    if item.last_verified_at is None:
        return True
    return timestamp - item.last_verified_at > resolved_policy.max_age_for(item)


def evaluate_currency(
    item: KnowledgeItem,
    *,
    as_of: datetime | None = None,
    policy: VerificationPolicy | None = None,
) -> CurrencyEvaluation:
    timestamp = as_of or now_utc()
    explanation: list[str] = []
    stale_reasons = list(item.metadata.get("staleness_reasons", []))

    if item.currency_state is CurrencyState.RETIRED:
        return CurrencyEvaluation(
            item_id=item.id,
            currency_state=CurrencyState.RETIRED,
            explanation=["item has been retired"],
            verification_due=False,
            stale_reasons=stale_reasons,
        )

    if item.currency_state is CurrencyState.SUPERSEDED:
        if item.valid_to is not None:
            explanation.append(f"valid_to closed at {item.valid_to.isoformat()}")
        else:
            explanation.append("item is already marked superseded")
        if item.successor_id:
            explanation.append(f"successor item: {item.successor_id}")
        return CurrencyEvaluation(
            item_id=item.id,
            currency_state=CurrencyState.SUPERSEDED,
            explanation=explanation,
            verification_due=False,
            stale_reasons=stale_reasons,
        )

    if item.valid_to is not None and item.valid_to <= timestamp:
        explanation.append(f"valid_to closed at {item.valid_to.isoformat()}")
        if item.successor_id:
            explanation.append(f"successor item: {item.successor_id}")
        return CurrencyEvaluation(
            item_id=item.id,
            currency_state=CurrencyState.SUPERSEDED,
            explanation=explanation,
            verification_due=False,
            stale_reasons=stale_reasons,
        )

    if item.currency_state is CurrencyState.STALE_PENDING_REVERIFICATION or stale_reasons:
        if stale_reasons:
            explanation.append("one or more dependencies moved and require human re-verification")
        else:
            explanation.append("item is already marked stale-pending-reverification")
        return CurrencyEvaluation(
            item_id=item.id,
            currency_state=CurrencyState.STALE_PENDING_REVERIFICATION,
            explanation=explanation,
            verification_due=verification_due(item, as_of=timestamp, policy=policy),
            stale_reasons=stale_reasons,
        )

    due = verification_due(item, as_of=timestamp, policy=policy)
    if due:
        explanation.append("verification age exceeds policy")
        return CurrencyEvaluation(
            item_id=item.id,
            currency_state=CurrencyState.STALE_PENDING_REVERIFICATION,
            explanation=explanation,
            verification_due=True,
            stale_reasons=stale_reasons,
        )

    explanation.append("item is open-validity and verification is current")
    return CurrencyEvaluation(
        item_id=item.id,
        currency_state=CurrencyState.LIVE,
        explanation=explanation,
        verification_due=False,
        stale_reasons=stale_reasons,
    )


def live_items(store: SQLiteKnowledgeStore) -> list[KnowledgeItem]:
    return store.get_many(include_states={CurrencyState.LIVE})


def record_verification(
    item: KnowledgeItem,
    *,
    by: str,
    outcome: VerificationOutcome | Literal["reaffirm", "supersede", "retire"],
    recorded_at: datetime | None = None,
    successor_id: str | None = None,
) -> RecordedVerification:
    timestamp = recorded_at or now_utc()
    resolved_outcome = VerificationOutcome(outcome)
    metadata = dict(item.metadata)

    if resolved_outcome is VerificationOutcome.REAFFIRM:
        metadata.pop("staleness_reasons", None)
        updated = item.model_copy(
            update={
                "currency_state": CurrencyState.LIVE,
                "verified_state": VerifiedState.VERIFIED,
                "last_verified_at": timestamp,
                "verified_by": by,
                "metadata": metadata,
            }
        )
    elif resolved_outcome is VerificationOutcome.RETIRE:
        updated = item.model_copy(
            update={
                "currency_state": CurrencyState.RETIRED,
                "verified_state": VerifiedState.VERIFIED,
                "last_verified_at": timestamp,
                "verified_by": by,
                "valid_to": timestamp,
                "metadata": metadata,
            }
        )
    else:
        if successor_id is None:
            raise ValueError("successor_id is required for supersede verification outcomes")
        updated = item.model_copy(
            update={
                "currency_state": CurrencyState.SUPERSEDED,
                "verified_state": VerifiedState.VERIFIED,
                "last_verified_at": timestamp,
                "verified_by": by,
                "valid_to": timestamp,
                "successor_id": successor_id,
                "metadata": metadata,
            }
        )

    return RecordedVerification(item=updated, outcome=resolved_outcome, recorded_at=timestamp)


def register_authority_change(
    *,
    authority_id: str,
    new_version: str,
    changed_at: datetime,
    graph: GraphStore,
    store: SQLiteKnowledgeStore,
) -> ImpactResult:
    reason = f"external authority {authority_id} changed to version {new_version}"
    return CurrencyPropagator(graph=graph, store=store).propagate_dependency_change(
        authority_id,
        changed_at=changed_at,
        reason=reason,
    )
