# SPDX-License-Identifier: Apache-2.0

"""Safety refusals for durable projections that cannot prove their immutable origin."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from solomon.currency.models import now_utc
from solomon.graph.suggestions import SuggestionDecision
from solomon.operations.assertion_audit_projection import AssertionAuditProjection
from solomon.operations.assertion_projection import AssertionConfirmationProjection
from solomon.operations.authority_projection import AuthorityChangeProjection
from solomon.operations.candidate_promotion_projection import CandidatePromotionProjection
from solomon.operations.evidence_projection import EvidenceIngestionProjection
from solomon.operations.execution import OperationRequiresIntervention
from solomon.operations.models import OperationRecord, OperationScope, OperationStatus, OperationType
from solomon.operations.reverification_projection import SourceRevisionReverificationProjection
from solomon.operations.suggestion_confirmation_projection import SuggestionConfirmationProjection
from solomon.operations.suggestion_projection import SuggestionGenerationProjection
from solomon.sources.models import CandidateClaimStatus
from solomon.sources.store import CandidateClaimNotFoundError, SourceDocumentNotFoundError

_SCOPE = OperationScope(tenant_id="tenant-a", matter_id="matter-a", client_id="client-a")


def _operation(operation_type: OperationType, **updates: Any) -> OperationRecord:
    timestamp = now_utc()
    values: dict[str, Any] = {
        "operation_type": operation_type,
        "scope": _SCOPE,
        "actor_id": "reviewer-a",
        "authorization_context": {"service_access": "review"},
        "correlation_id": "projection-guard-test",
        "idempotency_key": f"projection-guard:{operation_type.value}",
        "status": OperationStatus.CLAIMED,
        "lease_owner": "worker-a",
        "lease_expires_at": timestamp + timedelta(seconds=30),
    }
    values.update(updates)
    return OperationRecord(**values)


def test_candidate_promotion_refuses_unreconstructible_or_unsafe_origin() -> None:
    projection = CandidatePromotionProjection(authority_service=SimpleNamespace(), operation_store=object())
    with pytest.raises(OperationRequiresIntervention, match="not candidate promotion"):
        projection.apply(_operation(OperationType.ASSERTION_CONFIRM), "worker-a")
    with pytest.raises(OperationRequiresIntervention, match="incomplete"):
        projection.apply(
            _operation(
                OperationType.CANDIDATE_PROMOTION,
                status=OperationStatus.QUEUED,
                lease_owner=None,
                lease_expires_at=None,
            ),
            "worker-a",
        )

    operation = _operation(
        OperationType.CANDIDATE_PROMOTION,
        source_resource_id="candidate-a",
        target_resource_id="item-a",
    )

    def missing_candidate(_: str) -> Any:
        raise CandidateClaimNotFoundError("candidate-a")

    projection = CandidatePromotionProjection(
        authority_service=SimpleNamespace(document_store=SimpleNamespace(get_candidate=missing_candidate)),
        operation_store=object(),
    )
    with pytest.raises(OperationRequiresIntervention, match="cannot be reconstructed"):
        projection.apply(operation, "worker-a")

    candidate = SimpleNamespace(id="candidate-a", status=CandidateClaimStatus.PENDING, promotion_item_id=None)
    authority = SimpleNamespace(
        document_store=SimpleNamespace(get_candidate=lambda _: candidate),
        _get_item=lambda _: SimpleNamespace(matter_id="other", client_id="client-a", metadata={}),
    )
    with pytest.raises(OperationRequiresIntervention, match="scope"):
        CandidatePromotionProjection(authority_service=authority, operation_store=object()).apply(operation, "worker-a")

    authority._get_item = lambda _: SimpleNamespace(
        matter_id="matter-a", client_id="client-a", metadata={"source_candidate_id": "other"}
    )
    with pytest.raises(OperationRequiresIntervention, match="provenance"):
        CandidatePromotionProjection(authority_service=authority, operation_store=object()).apply(operation, "worker-a")

    candidate.status = CandidateClaimStatus.DEFERRED
    authority._get_item = lambda _: SimpleNamespace(
        id="item-a", matter_id="matter-a", client_id="client-a", metadata={"source_candidate_id": candidate.id}
    )
    with pytest.raises(OperationRequiresIntervention, match="no longer safe"):
        CandidatePromotionProjection(authority_service=authority, operation_store=object()).apply(operation, "worker-a")


def test_evidence_and_suggestion_generation_refuse_wrong_origin_or_scope() -> None:
    evidence = EvidenceIngestionProjection(document_store=object(), audit=object(), operation_store=object())
    with pytest.raises(OperationRequiresIntervention, match="not source evidence"):
        evidence.apply(_operation(OperationType.SUGGESTION_GENERATION), "worker-a")
    with pytest.raises(OperationRequiresIntervention, match="incomplete"):
        evidence.apply(
            _operation(
                OperationType.EVIDENCE_INGESTION,
                status=OperationStatus.QUEUED,
                lease_owner=None,
                lease_expires_at=None,
            ),
            "worker-a",
        )

    operation = _operation(
        OperationType.EVIDENCE_INGESTION,
        source_resource_id="source-a",
        target_resource_id="document-a",
    )

    def missing_document(_: str) -> Any:
        raise SourceDocumentNotFoundError("document-a")

    evidence = EvidenceIngestionProjection(
        document_store=SimpleNamespace(get_document=missing_document), audit=object(), operation_store=object()
    )
    with pytest.raises(OperationRequiresIntervention, match="cannot be reconstructed"):
        evidence.apply(operation, "worker-a")
    evidence = EvidenceIngestionProjection(
        document_store=SimpleNamespace(get_document=lambda _: SimpleNamespace(source_id="source-other")),
        audit=object(),
        operation_store=object(),
    )
    with pytest.raises(OperationRequiresIntervention, match="does not match"):
        evidence.apply(operation, "worker-a")

    suggestion_generation = SuggestionGenerationProjection(
        authority_service=SimpleNamespace(),
        operation_store=object(),
    )
    with pytest.raises(OperationRequiresIntervention, match="not suggestion generation"):
        suggestion_generation.apply(_operation(OperationType.EVIDENCE_INGESTION), "worker-a")
    with pytest.raises(OperationRequiresIntervention, match="incomplete"):
        suggestion_generation.apply(
            _operation(
                OperationType.SUGGESTION_GENERATION,
                status=OperationStatus.QUEUED,
                lease_owner=None,
                lease_expires_at=None,
            ),
            "worker-a",
        )
    suggestion_generation = SuggestionGenerationProjection(
        authority_service=SimpleNamespace(
            _get_item=lambda _: SimpleNamespace(matter_id="other", client_id="client-a")
        ),
        operation_store=object(),
    )
    with pytest.raises(OperationRequiresIntervention, match="scope"):
        suggestion_generation.apply(
            _operation(OperationType.SUGGESTION_GENERATION, target_resource_id="item-a"), "worker-a"
        )


def test_authority_projection_refuses_incomplete_or_invalid_change_payload() -> None:
    projection = AuthorityChangeProjection(authority_service=SimpleNamespace(), operation_store=object())
    with pytest.raises(OperationRequiresIntervention, match="not an authority"):
        projection.apply(_operation(OperationType.ASSERTION_CONFIRM), "worker-a")
    with pytest.raises(OperationRequiresIntervention, match="incomplete or not claimed"):
        projection.apply(
            _operation(
                OperationType.AUTHORITY_CHANGE_PROPAGATION,
                status=OperationStatus.QUEUED,
                lease_owner=None,
                lease_expires_at=None,
            ),
            "worker-a",
        )
    with pytest.raises(OperationRequiresIntervention, match="payload is incomplete"):
        projection.apply(
            _operation(OperationType.AUTHORITY_CHANGE_PROPAGATION, target_resource_id="authority-a"), "worker-a"
        )
    with pytest.raises(OperationRequiresIntervention, match="timestamp is invalid"):
        projection.apply(
            _operation(
                OperationType.AUTHORITY_CHANGE_PROPAGATION,
                target_resource_id="authority-a",
                payload={"new_version": "2026.1", "changed_at": "not-a-timestamp"},
            ),
            "worker-a",
        )


def test_assertion_confirmation_refuses_non_governed_stale_or_cross_scope_recovery() -> None:
    projection = AssertionConfirmationProjection(lifecycle=SimpleNamespace(), operation_store=object())
    with pytest.raises(OperationRequiresIntervention, match="not an assertion confirmation"):
        projection.apply(_operation(OperationType.EVIDENCE_INGESTION), "worker-a")
    with pytest.raises(OperationRequiresIntervention, match="not actively claimed"):
        projection.apply(
            _operation(
                OperationType.ASSERTION_CONFIRM,
                status=OperationStatus.QUEUED,
                lease_owner=None,
                lease_expires_at=None,
            ),
            "worker-a",
        )
    with pytest.raises(OperationRequiresIntervention, match="no assertion ID"):
        projection.apply(_operation(OperationType.ASSERTION_CONFIRM), "worker-a")

    operation = _operation(OperationType.ASSERTION_CONFIRM, assertion_id="assertion-a")
    assertion: Any = SimpleNamespace(
        source="deterministic",
        matter_id="matter-a",
        client_id="client-a",
        created_by="curator-a",
        decision=SuggestionDecision.PENDING,
    )
    with pytest.raises(OperationRequiresIntervention, match="not governed"):
        projection._validate(operation, assertion)
    assertion.source = "human"
    assertion.matter_id = "other"
    with pytest.raises(OperationRequiresIntervention, match="scope"):
        projection._validate(operation, assertion)
    assertion.matter_id = "matter-a"
    assertion.created_by = "reviewer-a"
    with pytest.raises(OperationRequiresIntervention, match="creator"):
        projection._validate(operation, assertion)
    assertion.created_by = "curator-a"
    assertion.decision = SuggestionDecision.REJECTED
    with pytest.raises(OperationRequiresIntervention, match="terminal negative"):
        projection._validate(operation, assertion)
    assertion.decision = SuggestionDecision.DEFERRED
    operation = operation.model_copy(update={"requested_transition": "deferred"})
    with pytest.raises(OperationRequiresIntervention, match="deferred"):
        projection._validate(operation, assertion)

    confirmed: Any = SimpleNamespace(
        id="assertion-a",
        decision=SuggestionDecision.CONFIRMED,
        suggested_edge=SimpleNamespace(id="edge-a"),
    )
    projection = AssertionConfirmationProjection(
        lifecycle=SimpleNamespace(_get_assertion=lambda _: confirmed), operation_store=object()
    )
    with pytest.raises(OperationRequiresIntervention, match="different edge"):
        projection._confirm_assertion(confirmed, SimpleNamespace(id="edge-other"))
    confirmed.decision = SuggestionDecision.WITHDRAWN
    with pytest.raises(OperationRequiresIntervention, match="became terminal"):
        projection._confirm_assertion(confirmed, SimpleNamespace(id="edge-a"))


def test_suggestion_confirmation_and_reverification_refuse_stale_lineage() -> None:
    projection = SuggestionConfirmationProjection(lifecycle=SimpleNamespace(), operation_store=object())
    with pytest.raises(OperationRequiresIntervention, match="not a suggestion confirmation"):
        projection.apply(_operation(OperationType.ASSERTION_CONFIRM), "worker-a")
    with pytest.raises(OperationRequiresIntervention, match="incomplete"):
        projection.apply(
            _operation(
                OperationType.SUGGESTION_CONFIRM,
                status=OperationStatus.QUEUED,
                lease_owner=None,
                lease_expires_at=None,
            ),
            "worker-a",
        )

    suggestion = SimpleNamespace(item_id="item-a")
    projection = SuggestionConfirmationProjection(
        lifecycle=SimpleNamespace(
            _graph=SimpleNamespace(get_dependency_suggestion=lambda _: suggestion),
            _get_item=lambda _: SimpleNamespace(matter_id="other", client_id="client-a"),
        ),
        operation_store=object(),
    )
    with pytest.raises(OperationRequiresIntervention, match="scope"):
        projection.apply(_operation(OperationType.SUGGESTION_CONFIRM, suggestion_id="suggestion-a"), "worker-a")

    operation = _operation(
        OperationType.SUGGESTION_CONFIRM,
        suggestion_id="suggestion-a",
        payload={"expected_state_version": 1},
    )
    latest: Any = SimpleNamespace(
        id="suggestion-a",
        decision=SuggestionDecision.CONFIRMED,
        suggested_edge=SimpleNamespace(id="edge-a"),
        state_version=1,
    )
    projection = SuggestionConfirmationProjection(
        lifecycle=SimpleNamespace(_graph=SimpleNamespace(get_dependency_suggestion=lambda _: latest)),
        operation_store=object(),
    )
    with pytest.raises(OperationRequiresIntervention, match="different edge"):
        projection._confirm_suggestion(operation, latest, SimpleNamespace(id="edge-other"))
    latest.decision = SuggestionDecision.REJECTED
    with pytest.raises(OperationRequiresIntervention, match="became terminal"):
        projection._confirm_suggestion(operation, latest, SimpleNamespace(id="edge-a"))
    latest.decision = SuggestionDecision.PENDING
    latest.state_version = 2
    with pytest.raises(OperationRequiresIntervention, match="no longer matches"):
        projection._confirm_suggestion(operation, latest, SimpleNamespace(id="edge-a"))

    reverification = SourceRevisionReverificationProjection(lifecycle=SimpleNamespace(), operation_store=object())
    with pytest.raises(OperationRequiresIntervention, match="not source revision"):
        reverification.apply(_operation(OperationType.ASSERTION_CONFIRM), "worker-a")
    with pytest.raises(OperationRequiresIntervention, match="incomplete"):
        reverification.apply(
            _operation(
                OperationType.SOURCE_REVISION_REVERIFY,
                status=OperationStatus.QUEUED,
                lease_owner=None,
                lease_expires_at=None,
            ),
            "worker-a",
        )
    with pytest.raises(OperationRequiresIntervention, match="no document lineage"):
        reverification.apply(
            _operation(OperationType.SOURCE_REVISION_REVERIFY, assertion_id="assertion-a"), "worker-a"
        )

    revision_operation = _operation(
        OperationType.SOURCE_REVISION_REVERIFY,
        assertion_id="assertion-a",
        source_resource_id="document-a",
        target_resource_id="document-b",
    )
    assertion: Any = SimpleNamespace(matter_id="other", client_id="client-a", source_document_id="document-a")
    with pytest.raises(OperationRequiresIntervention, match="scope"):
        reverification._validate(revision_operation, assertion)
    assertion.matter_id = "matter-a"
    assertion.source_document_id = "document-other"
    with pytest.raises(OperationRequiresIntervention, match="not bound"):
        reverification._validate(revision_operation, assertion)
    assertion.source_document_id = "document-a"

    def missing_replacement(_: str) -> Any:
        raise KeyError("document-b")

    reverification = SourceRevisionReverificationProjection(
        lifecycle=SimpleNamespace(_document_store=SimpleNamespace(get_document=missing_replacement)),
        operation_store=object(),
    )
    with pytest.raises(OperationRequiresIntervention, match="cannot be reconstructed"):
        reverification._validate(revision_operation, assertion)
    reverification = SourceRevisionReverificationProjection(
        lifecycle=SimpleNamespace(
            _document_store=SimpleNamespace(
                get_document=lambda _: SimpleNamespace(previous_version_id="document-other")
            )
        ),
        operation_store=object(),
    )
    with pytest.raises(OperationRequiresIntervention, match="does not continue"):
        reverification._validate(revision_operation, assertion)


def test_assertion_audit_refuses_unreviewed_transitions_and_scope_mismatch() -> None:
    projection = AssertionAuditProjection(lifecycle=SimpleNamespace(), operation_store=object())
    with pytest.raises(OperationRequiresIntervention, match="not an assertion audit"):
        projection.apply(_operation(OperationType.ASSERTION_CONFIRM), "worker-a")
    with pytest.raises(OperationRequiresIntervention, match="incomplete"):
        projection.apply(
            _operation(
                OperationType.ASSERTION_TRANSITION,
                status=OperationStatus.QUEUED,
                lease_owner=None,
                lease_expires_at=None,
            ),
            "worker-a",
        )
    assertion = SimpleNamespace(matter_id="other", client_id="client-a")
    projection = AssertionAuditProjection(
        lifecycle=SimpleNamespace(get=lambda *args, **kwargs: assertion), operation_store=object()
    )
    with pytest.raises(OperationRequiresIntervention, match="scope"):
        projection.apply(_operation(OperationType.ASSERTION_CREATE, assertion_id="assertion-a"), "worker-a")

    transition = _operation(
        OperationType.ASSERTION_TRANSITION,
        assertion_id="assertion-a",
        requested_transition="withdrawn",
    )
    with pytest.raises(OperationRequiresIntervention, match="not a terminal"):
        projection._event_for(transition, SuggestionDecision.PENDING)
    with pytest.raises(OperationRequiresIntervention, match="does not match"):
        projection._event_for(transition, SuggestionDecision.REJECTED)
    rejected = projection._event_for(
        transition.model_copy(update={"requested_transition": "rejected"}),
        SuggestionDecision.REJECTED,
    )
    assert rejected == (
        "dependency_assertion_rejected",
        "review_audit_id",
    )
