# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from solomon.api.schemas import SolomonModel
from solomon.currency.models import KnowledgeItem, new_uuid7, now_utc


class VerificationLifecycleState(str, Enum):
    REQUESTED = "verification_requested"
    ASSIGNED = "assigned"
    IN_REVIEW = "in_review"
    REAFFIRMED = "reaffirmed"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class VerificationLifecycleEvent(SolomonModel):
    event_id: str = Field(default_factory=new_uuid7)
    item_id: str
    state: VerificationLifecycleState
    actor_id: str
    occurred_at: datetime = Field(default_factory=now_utc)
    reviewer_id: str | None = None
    role: str | None = None
    basis: str | None = None
    source_ref: str | None = None
    policy_version: str | None = None
    credence_policy_version: str | None = None
    policy_snapshot: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        from solomon.currency.models import _ensure_aware_utc

        return _ensure_aware_utc(value)


def verification_history(item: KnowledgeItem) -> list[VerificationLifecycleEvent]:
    events = item.metadata.get("verification_events", [])
    if not isinstance(events, list):
        return []
    return [VerificationLifecycleEvent.model_validate(event) for event in events]


def append_verification_event(item: KnowledgeItem, event: VerificationLifecycleEvent) -> KnowledgeItem:
    events = [entry.model_dump(mode="json") for entry in verification_history(item)]
    events.append(event.model_dump(mode="json"))
    metadata = {
        **item.metadata,
        "verification_events": events,
        "verification_status": event.state.value,
    }
    if event.reviewer_id is not None:
        metadata["verification_reviewer_id"] = event.reviewer_id
    if event.role is not None:
        metadata["verification_reviewer_role"] = event.role
    return item.model_copy(update={"metadata": metadata})


def latest_verification_event(item: KnowledgeItem) -> VerificationLifecycleEvent | None:
    events = verification_history(item)
    return events[-1] if events else None


def lifecycle_state_for_outcome(outcome: str) -> VerificationLifecycleState:
    return {
        "reaffirm": VerificationLifecycleState.REAFFIRMED,
        "supersede": VerificationLifecycleState.SUPERSEDED,
        "retire": VerificationLifecycleState.RETIRED,
    }[outcome]
