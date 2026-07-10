# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.currency.engine import VerificationOutcome
from solomon.currency.models import (
    CredenceTier,
    KnowledgeContentRole,
    KnowledgeItem,
    KnowledgeKind,
    SourceKind,
)
from solomon.currency.prediction import PendingAuthorityAmendment
from solomon.graph.models import EdgeConfidence, EdgeType


class IngestRequest(SolomonModel):
    kind: KnowledgeKind
    content: str = Field(min_length=1)
    source_kind: SourceKind
    source_ref: str = Field(min_length=1)
    author: str | None = None
    content_role: KnowledgeContentRole | None = None
    matter_id: str | None = None
    client_id: str | None = None
    valid_from: datetime | None = None
    ingested_at: datetime | None = None


class RecallRequest(SolomonModel):
    query: str
    matter_id: str | None = None
    client_id: str | None = None
    review_mode: bool = False
    limit: int = 10
    max_context_tokens: int | None = Field(default=None, ge=1)


class VerificationRequest(SolomonModel):
    by: str
    outcome: VerificationOutcome
    successor_id: str | None = None
    recorded_at: datetime | None = None


class AuthorityChangeRequest(SolomonModel):
    new_version: str
    changed_at: str


class ContestRequest(SolomonModel):
    lawyer_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    proposed_correction: str | None = None
    actor_tier: CredenceTier = CredenceTier.VERIFIED
    contested_at: datetime | None = None


class ContestResponse(SolomonModel):
    item: KnowledgeItem
    correction_item: KnowledgeItem | None = None
    impact: dict[str, Any]


class AffirmRequest(SolomonModel):
    lawyer_id: str = Field(min_length=1)
    actor_tier: CredenceTier = CredenceTier.FIRM_AUTHORITATIVE
    correction_item_id: str | None = None
    affirmed_at: datetime | None = None


class AffirmResponse(SolomonModel):
    item: KnowledgeItem
    correction_item: KnowledgeItem | None = None
    superseded: bool = False


class PinRequest(SolomonModel):
    lawyer_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    actor_tier: CredenceTier = CredenceTier.FIRM_AUTHORITATIVE
    pinned_at: datetime | None = None


class ReferenceExtractionRequest(SolomonModel):
    content: str = Field(min_length=1)


class StalenessPredictionRequest(SolomonModel):
    pending_amendments: list[PendingAuthorityAmendment]
    lookahead_days: int = Field(default=180, ge=1)
    as_of: str | None = None


class DependencyRequest(SolomonModel):
    source_id: str
    target_id: str
    edge_type: EdgeType
    target_kind: str
    confidence: EdgeConfidence = EdgeConfidence.HUMAN_ASSERTED
    created_by: str | None = None
    reason: str | None = None


class DependencySuggestionRequest(SolomonModel):
    item_id: str
    use_llm: bool = False


class DependencySuggestionDecisionRequest(SolomonModel):
    by: str = Field(min_length=1)


class AnswerRequest(SolomonModel):
    query: str
    matter_id: str | None = None
    client_id: str | None = None
    matter_sensitivity: Literal["standard", "confidential", "strict"] = "standard"
    limit: int = Field(default=5, ge=1)
    max_context_tokens: int | None = Field(default=1200, ge=1)
    max_tokens: int = Field(default=1024, ge=1)
    temperature: float = Field(default=0.0, ge=0.0)


class AnswerResponse(SolomonModel):
    query: str
    text: str
    model: dict[str, Any]
    recalled: list[dict[str, Any]]
    prompt: dict[str, Any]
    primitive_plan: dict[str, Any]


class WhyTrace(SolomonModel):
    item: KnowledgeItem
    currency: dict[str, Any]
    dependencies: list[dict[str, Any]]
    dependents: list[dict[str, Any]]
    provenance: dict[str, Any]
    credence_tier: str
    verification: dict[str, Any]


class PrimitivePlanStep(SolomonModel):
    primitive: str
    args: dict[str, Any] = Field(default_factory=dict)


class PrimitivePlanRequest(SolomonModel):
    plan_id: str | None = None
    steps: list[PrimitivePlanStep] = Field(min_length=1)


class PrimitiveStepResult(SolomonModel):
    index: int
    primitive: str
    args_sha256: str
    result_sha256: str
    result_summary: dict[str, Any]
    result: Any


class PrimitivePlanExecution(SolomonModel):
    schema_id: str = "solomon.primitive_plan_execution.v1"
    plan_id: str
    plan: PrimitivePlanRequest
    store_state_sha256: str
    steps: list[PrimitiveStepResult]
    audit_event_hash: str


__all__ = [
    "IngestRequest",
    "RecallRequest",
    "VerificationRequest",
    "AuthorityChangeRequest",
    "ContestRequest",
    "ContestResponse",
    "AffirmRequest",
    "AffirmResponse",
    "PinRequest",
    "ReferenceExtractionRequest",
    "StalenessPredictionRequest",
    "DependencyRequest",
    "DependencySuggestionRequest",
    "DependencySuggestionDecisionRequest",
    "AnswerRequest",
    "AnswerResponse",
    "WhyTrace",
    "PrimitivePlanStep",
    "PrimitivePlanRequest",
    "PrimitiveStepResult",
    "PrimitivePlanExecution",
]
