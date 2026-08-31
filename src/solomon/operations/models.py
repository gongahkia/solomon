# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field, field_validator, model_validator

from solomon.api.schemas import SolomonModel
from solomon.currency.models import _ensure_aware_utc, new_uuid7, now_utc


class OperationType(str, Enum):
    """The current bounded set of multi-stage knowledge operations."""

    ASSERTION_CREATE = "assertion_create"
    ASSERTION_CONFIRM = "assertion_confirm"
    ASSERTION_TRANSITION = "assertion_transition"
    SOURCE_REVISION_REVERIFY = "source_revision_reverify"
    AUTHORITY_CHANGE_PROPAGATION = "authority_change_propagation"
    EVIDENCE_INGESTION = "evidence_ingestion"
    SUGGESTION_GENERATION = "suggestion_generation"
    SUGGESTION_CONFIRM = "suggestion_confirm"
    CANDIDATE_PROMOTION = "candidate_promotion"


class OperationStatus(str, Enum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    RETRYING = "retrying"
    COMPLETED = "completed"
    TERMINAL_FAILED = "terminal_failed"
    OPERATOR_REQUIRED = "operator_required"


class OperationPhase(str, Enum):
    AUTHORITATIVE = "authoritative"
    SCHEDULED = "scheduled"
    GRAPH = "graph"
    CURRENCY = "currency"
    AUDIT = "audit"
    COMPLETED = "completed"


TERMINAL_OPERATION_STATUSES = frozenset(
    {OperationStatus.COMPLETED, OperationStatus.TERMINAL_FAILED, OperationStatus.OPERATOR_REQUIRED}
)

_ALLOWED_TRANSITIONS: dict[OperationStatus, frozenset[OperationStatus]] = {
    OperationStatus.QUEUED: frozenset(
        {
            OperationStatus.CLAIMED,
            OperationStatus.TERMINAL_FAILED,
            OperationStatus.OPERATOR_REQUIRED,
        }
    ),
    OperationStatus.CLAIMED: frozenset(
        {
            OperationStatus.QUEUED,
            OperationStatus.RETRYING,
            OperationStatus.COMPLETED,
            OperationStatus.TERMINAL_FAILED,
            OperationStatus.OPERATOR_REQUIRED,
        }
    ),
    OperationStatus.RETRYING: frozenset(
        {
            OperationStatus.CLAIMED,
            OperationStatus.TERMINAL_FAILED,
            OperationStatus.OPERATOR_REQUIRED,
        }
    ),
    OperationStatus.COMPLETED: frozenset(),
    OperationStatus.TERMINAL_FAILED: frozenset(),
    OperationStatus.OPERATOR_REQUIRED: frozenset(),
}


class OperationScope(SolomonModel):
    """Immutable tenant and knowledge scope for a durable operation."""

    tenant_id: str | None = Field(default=None, min_length=1, max_length=120)
    matter_id: str | None = Field(default=None, min_length=1, max_length=500)
    client_id: str | None = Field(default=None, min_length=1, max_length=500)

    @property
    def key(self) -> str:
        return "|".join((self.tenant_id or "", self.matter_id or "", self.client_id or ""))


class OperationRecord(SolomonModel):
    """A durable operation request and its current safe processing checkpoint."""

    id: str = Field(default_factory=new_uuid7)
    operation_type: OperationType
    scope: OperationScope
    actor_id: str = Field(min_length=1, max_length=500)
    authorization_context: dict[str, str] = Field(default_factory=dict)
    correlation_id: str = Field(min_length=1, max_length=500)
    causation_id: str | None = Field(default=None, min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=500)
    source_resource_id: str | None = Field(default=None, min_length=1, max_length=500)
    source_version: int | None = Field(default=None, ge=1)
    target_resource_id: str | None = Field(default=None, min_length=1, max_length=500)
    assertion_id: str | None = Field(default=None, min_length=1, max_length=500)
    suggestion_id: str | None = Field(default=None, min_length=1, max_length=500)
    requested_transition: str | None = Field(default=None, min_length=1, max_length=120)
    payload: dict[str, str | int | bool | None] = Field(default_factory=dict)
    status: OperationStatus = OperationStatus.QUEUED
    phase: OperationPhase = OperationPhase.SCHEDULED
    attempt_count: int = Field(default=0, ge=0)
    state_version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    last_successful_checkpoint: OperationPhase | None = None
    failure_category: str | None = Field(default=None, max_length=120)
    diagnostic: str | None = Field(default=None, max_length=500)
    next_eligible_retry_at: datetime | None = None
    lease_owner: str | None = Field(default=None, max_length=300)
    lease_expires_at: datetime | None = None
    result_entity_id: str | None = Field(default=None, max_length=500)
    result_edge_id: str | None = Field(default=None, max_length=500)
    audit_entry_hashes: list[str] = Field(default_factory=list)

    @field_validator("created_at", "updated_at", "next_eligible_retry_at", "lease_expires_at")
    @classmethod
    def normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return _ensure_aware_utc(value) if value is not None else None

    @field_validator("authorization_context")
    @classmethod
    def require_safe_authorization_context(cls, value: dict[str, str]) -> dict[str, str]:
        forbidden = {"credential", "token", "secret", "password", "authorization"}
        if any(key.lower() in forbidden for key in value):
            raise ValueError("authorization context must not contain credentials or tokens")
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def validate_lease_and_terminal_state(self) -> OperationRecord:
        if self.status is OperationStatus.CLAIMED:
            if self.lease_owner is None or self.lease_expires_at is None:
                raise ValueError("claimed operations require a durable lease owner and expiry")
        elif self.lease_owner is not None or self.lease_expires_at is not None:
            raise ValueError("only claimed operations may retain a lease")
        if self.status in TERMINAL_OPERATION_STATUSES and self.next_eligible_retry_at is not None:
            raise ValueError("terminal operations cannot be eligible for retry")
        if self.phase is OperationPhase.COMPLETED and self.status is not OperationStatus.COMPLETED:
            raise ValueError("only completed operations may use the completed phase")
        return self

    def with_transition(
        self,
        *,
        status: OperationStatus,
        phase: OperationPhase | None = None,
        checkpoint: OperationPhase | None = None,
        attempt_count: int | None = None,
        failure_category: str | None = None,
        diagnostic: str | None = None,
        next_eligible_retry_at: datetime | None = None,
        lease_owner: str | None = None,
        lease_expires_at: datetime | None = None,
        result_entity_id: str | None = None,
        result_edge_id: str | None = None,
        audit_entry_hashes: list[str] | None = None,
        updated_at: datetime | None = None,
    ) -> OperationRecord:
        if status is not self.status and status not in _ALLOWED_TRANSITIONS[self.status]:
            raise ValueError(f"invalid operation transition: {self.status.value} -> {status.value}")
        resolved_phase = phase or self.phase
        if status is OperationStatus.COMPLETED:
            resolved_phase = OperationPhase.COMPLETED
        return self.model_copy(
            update={
                "status": status,
                "phase": resolved_phase,
                "last_successful_checkpoint": checkpoint or self.last_successful_checkpoint,
                "attempt_count": self.attempt_count if attempt_count is None else attempt_count,
                "failure_category": failure_category,
                "diagnostic": diagnostic,
                "next_eligible_retry_at": next_eligible_retry_at,
                "lease_owner": lease_owner,
                "lease_expires_at": lease_expires_at,
                "result_entity_id": result_entity_id or self.result_entity_id,
                "result_edge_id": result_edge_id or self.result_edge_id,
                "audit_entry_hashes": audit_entry_hashes or self.audit_entry_hashes,
                "state_version": self.state_version + 1,
                "updated_at": updated_at or now_utc(),
            }
        )


class OperationHistoryEntry(SolomonModel):
    """Append-only explanation of an operation state change."""

    operation_id: str = Field(min_length=1)
    state_version: int = Field(ge=1)
    event: str = Field(min_length=1, max_length=120)
    status: OperationStatus
    phase: OperationPhase
    occurred_at: datetime = Field(default_factory=now_utc)
    actor_id: str | None = Field(default=None, max_length=500)
    detail: str | None = Field(default=None, max_length=500)

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        return _ensure_aware_utc(value)


def is_terminal(status: OperationStatus) -> bool:
    return status in TERMINAL_OPERATION_STATUSES


__all__ = [
    "OperationHistoryEntry",
    "OperationPhase",
    "OperationRecord",
    "OperationScope",
    "OperationStatus",
    "OperationType",
    "TERMINAL_OPERATION_STATUSES",
    "is_terminal",
]
