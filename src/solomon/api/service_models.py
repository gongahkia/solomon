# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from solomon.api.schemas import SolomonModel
from solomon.connectors import ConnectorConfiguration
from solomon.currency.contradiction import ConclusionPolarity
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
from solomon.graph.suggestions import AssertionEvidenceKind, DependencyAssertionType
from solomon.sources.models import DocumentSourceKind


class IngestRequest(SolomonModel):
    kind: KnowledgeKind
    content: str = Field(min_length=1)
    source_kind: SourceKind
    source_ref: str = Field(min_length=1)
    conclusion: str | None = None
    conclusion_polarity: ConclusionPolarity | None = None
    author: str | None = None
    content_role: KnowledgeContentRole | None = None
    matter_id: str | None = None
    client_id: str | None = None
    valid_from: datetime | None = None
    ingested_at: datetime | None = None
    source_document_id: str | None = None
    source_document_version: int | None = Field(default=None, ge=1)
    previous_source_document_id: str | None = None
    source_document_span_start: int | None = Field(default=None, ge=0)
    source_document_span_end: int | None = Field(default=None, ge=1)


class DocumentSourceRequest(SolomonModel):
    source_id: str | None = Field(default=None, min_length=1)
    name: str = Field(min_length=1, max_length=120)
    kind: DocumentSourceKind
    root_ref: str = Field(min_length=1)
    enabled: bool = True
    config: ConnectorConfiguration = Field(default_factory=ConnectorConfiguration)


class SourceDocumentIngestRequest(SolomonModel):
    external_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    mime_type: str | None = None
    content: str | None = None
    content_base64: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_content(self) -> SourceDocumentIngestRequest:
        if (self.content is None) == (self.content_base64 is None):
            raise ValueError("exactly one of content or content_base64 is required")
        return self


class CandidateClaimPromotionRequest(SolomonModel):
    by: str = Field(min_length=1)
    kind: KnowledgeKind = KnowledgeKind.NOTE
    source_kind: SourceKind = SourceKind.MATTER_DOC
    author: str | None = None
    matter_id: str | None = None
    client_id: str | None = None
    conclusion: str | None = None
    conclusion_polarity: ConclusionPolarity | None = None


class CandidateClaimRejectionRequest(SolomonModel):
    by: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class CandidateClaimDeferralRequest(SolomonModel):
    by: str = Field(min_length=1)
    reason: str = Field(min_length=1)


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
    basis: str | None = None
    source_ref: str | None = None
    successor_id: str | None = None
    recorded_at: datetime | None = None


class ReviewTaskAssignmentRequest(SolomonModel):
    reviewer_id: str = Field(min_length=1)
    assigned_by: str = Field(min_length=1)


class ReviewTaskStartRequest(SolomonModel):
    reviewer_id: str = Field(min_length=1)


class ReviewTaskResolutionRequest(SolomonModel):
    reviewer_id: str = Field(min_length=1)
    verification: VerificationRequest


class VerificationAssignmentRequest(SolomonModel):
    assigned_by: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    role: str | None = None
    basis: str | None = None
    source_ref: str | None = None
    assigned_at: datetime | None = None


class VerificationReviewRequest(SolomonModel):
    reviewer_id: str = Field(min_length=1)
    basis: str | None = None
    source_ref: str | None = None
    started_at: datetime | None = None


class AuthorityChangeRequest(SolomonModel):
    new_version: str
    changed_at: str


class AuthorityEventRequest(SolomonModel):
    source_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    authority_id: str = Field(min_length=1)
    previous_version: str | None = None
    new_version: str = Field(min_length=1)
    changed_at: datetime
    evidence_url: str | None = None
    evidence_sha256: str | None = None
    diff: dict[str, Any] = Field(default_factory=dict)


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
    reason: str | None = Field(default=None, min_length=1)
    matter_id: str | None = None
    client_id: str | None = None


class DependencyAssertionCreateRequest(SolomonModel):
    """Create a governed assertion; its direction is source knowledge item -> target."""

    item_id: str = Field(min_length=1)
    source_document_id: str = Field(min_length=1)
    source_document_version: int = Field(ge=1)
    target_kind: Literal["knowledge_item", "external_authority"]
    target_item_id: str | None = None
    authority_source_id: str | None = None
    authority_identifier: str | None = None
    assertion_type: DependencyAssertionType
    evidence_kind: AssertionEvidenceKind
    quote: str | None = None
    quote_start: int | None = Field(default=None, ge=0)
    quote_end: int | None = Field(default=None, ge=1)
    commentary: str | None = None
    rationale: str = Field(min_length=1, max_length=4_000)
    created_by: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=255)
    origin: Literal["human", "trusted_upstream"] = "human"
    trusted_upstream_ref: str | None = Field(default=None, min_length=1)
    revision_of: str | None = Field(default=None, min_length=1)
    correlation_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_target_and_evidence(self) -> DependencyAssertionCreateRequest:
        if self.target_kind == "knowledge_item":
            if not self.target_item_id or self.authority_source_id or self.authority_identifier:
                raise ValueError("knowledge-item target requires target_item_id only")
        elif not self.authority_source_id or not self.authority_identifier or self.target_item_id:
            raise ValueError(
                "external authority target requires registered authority_source_id and authority_identifier"
            )
        if self.evidence_kind is AssertionEvidenceKind.QUOTE:
            if not self.quote or self.quote_start is None or self.quote_end is None:
                raise ValueError("quote evidence requires quote, quote_start, and quote_end")
            if self.quote_end <= self.quote_start:
                raise ValueError("quote_end must be after quote_start")
            if self.commentary is not None:
                raise ValueError("quote evidence cannot include commentary")
        elif (
            not self.commentary or self.quote is not None or self.quote_start is not None or self.quote_end is not None
        ):
            raise ValueError("commentary evidence requires commentary only")
        if self.origin == "trusted_upstream" and self.trusted_upstream_ref is None:
            raise ValueError("trusted upstream assertions require trusted_upstream_ref")
        if self.origin == "human" and self.trusted_upstream_ref is not None:
            raise ValueError("human assertions cannot claim trusted_upstream_ref")
        return self


class DependencyAssertionDecisionRequest(SolomonModel):
    by: str = Field(min_length=1)
    decision: Literal["confirmed", "rejected", "deferred"]
    reason: str | None = Field(default=None, min_length=1, max_length=4_000)
    expected_state_version: int | None = Field(default=None, ge=1)
    matter_id: str | None = None
    client_id: str | None = None

    @model_validator(mode="after")
    def validate_reason(self) -> DependencyAssertionDecisionRequest:
        if self.decision == "deferred" and self.reason is None:
            raise ValueError("a reason is required when deferring a dependency assertion")
        return self


class DependencyAssertionWithdrawRequest(SolomonModel):
    by: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=4_000)
    expected_state_version: int | None = Field(default=None, ge=1)
    matter_id: str | None = None
    client_id: str | None = None


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
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
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
    "DocumentSourceRequest",
    "SourceDocumentIngestRequest",
    "CandidateClaimPromotionRequest",
    "CandidateClaimRejectionRequest",
    "CandidateClaimDeferralRequest",
    "RecallRequest",
    "VerificationRequest",
    "ReviewTaskAssignmentRequest",
    "ReviewTaskStartRequest",
    "ReviewTaskResolutionRequest",
    "VerificationAssignmentRequest",
    "VerificationReviewRequest",
    "AuthorityChangeRequest",
    "AuthorityEventRequest",
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
    "DependencyAssertionCreateRequest",
    "DependencyAssertionDecisionRequest",
    "DependencyAssertionWithdrawRequest",
    "AnswerRequest",
    "AnswerResponse",
    "WhyTrace",
    "PrimitivePlanStep",
    "PrimitivePlanRequest",
    "PrimitiveStepResult",
    "PrimitivePlanExecution",
]
