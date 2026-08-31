# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone
from time import sleep
from typing import Any, cast

from solomon.api.service_models import (
    AuthorityChangeRequest,
    DependencyAssertionCreateRequest,
    DependencyAssertionDecisionRequest,
    DependencyAssertionWithdrawRequest,
    DependencyRequest,
    DependencySuggestionDecisionRequest,
    DependencySuggestionRequest,
    ReferenceExtractionRequest,
    StalenessPredictionRequest,
    VerificationAssignmentRequest,
    VerificationRequest,
    VerificationReviewRequest,
)
from solomon.api.services.base import ServiceContext, ServiceDelegate
from solomon.api.services.common import digest, parse_iso_datetime
from solomon.api.services.dependency_assertions import GovernedDependencyAssertionLifecycle
from solomon.api.services.dependency_suggestions import (
    DependencySuggestionLifecycle,
    source_document_offset,
    source_document_value,
    source_document_version,
)
from solomon.audit.journal import AuditAttribution, sign_verification_attestation
from solomon.currency.contradiction import (
    ContradictionSignal,
    append_contradiction_signal,
    contradictions_for_item,
    detect_same_authority_opposite_conclusions,
)
from solomon.currency.models import CurrencyState, KnowledgeContentRole, KnowledgeItem, VerifiedState
from solomon.currency.prediction import StalenessRiskReport, predict_staleness_risk
from solomon.currency.verification import (
    VerificationLifecycleEvent,
    VerificationLifecycleState,
    append_verification_event,
    latest_verification_event,
    lifecycle_state_for_outcome,
    verification_history,
)
from solomon.errors import BadRequestError, NotFoundError
from solomon.graph.models import DependencyEdge, EdgeType
from solomon.graph.propagation import CurrencyPropagator
from solomon.graph.suggestions import (
    DependencySuggestion,
    ReferenceExtraction,
    SuggestionDecision,
    extract_defined_terms_and_citations,
    suggest_authority_dependencies,
    suggest_authority_dependencies_with_llm,
)
from solomon.graph.visualization import GraphFormat, dependency_graph_view, render_dependency_graph
from solomon.operations.assertion_audit_projection import AssertionAuditProjection
from solomon.operations.assertion_projection import AssertionConfirmationProjection
from solomon.operations.authority_projection import AuthorityChangeProjection
from solomon.operations.evidence_projection import EvidenceIngestionProjection
from solomon.operations.execution import OperationRequiresIntervention, OperationRunner
from solomon.operations.failure_injection import OperationFailureInjector
from solomon.operations.models import OperationRecord, OperationScope, OperationStatus, OperationType
from solomon.operations.reverification_projection import SourceRevisionReverificationProjection
from solomon.operations.suggestion_projection import SuggestionGenerationProjection
from solomon.orchestrator.models import ModelRouter
from solomon.sources.store import SourceDocumentNotFoundError


class AuthorityService(ServiceDelegate):
    def __init__(self, context: ServiceContext) -> None:
        super().__init__(context)
        self._failure_injector = OperationFailureInjector()
        self._operation_runner = OperationRunner(store=self.operation_store, dispatch=self._dispatch_operation)
        self._dependency_lifecycle = DependencySuggestionLifecycle(
            graph=self.graph,
            audit=self.audit,
            currency_cache=self.currency_cache,
            get_item=self._get_item,
            on_confirmed_edge=self._detect_for_edge,
        )
        self._assertion_lifecycle = GovernedDependencyAssertionLifecycle(
            graph=self.graph,
            audit=self.audit,
            currency_cache=self.currency_cache,
            get_item=self._get_item,
            document_store=self.document_store,
            authority_sources=self.authority_sources,
            authority_identifiers=self.authority_identifiers,
            on_confirmed_edge=self._detect_for_edge,
            schedule_creation=self.record_assertion_creation,
            schedule_confirmation=self._schedule_assertion_confirmation,
            schedule_transition=self.record_assertion_transition,
        )

    def set_operation_failure_injector(self, injector: OperationFailureInjector) -> None:
        """Install a test-only deterministic failure injector; no public route calls this method."""

        self._failure_injector = injector

    def run_operation_once(self, *, worker_id: str, now: datetime | None = None) -> OperationRecord | None:
        return self._operation_runner.run_once(worker_id=worker_id, now=now)

    def _schedule_assertion_confirmation(
        self,
        assertion: DependencySuggestion,
        request: DependencyAssertionDecisionRequest,
        *,
        idempotency_suffix: str | None = None,
    ) -> DependencyEdge:
        if assertion.decision is SuggestionDecision.CONFIRMED:
            try:
                return self.graph.get_edge(assertion.suggested_edge.id)
            except KeyError:
                pass
        self._failure_injector.hit("before_authoritative_write")
        operation, _ = self.operation_store.create(
            OperationRecord(
                operation_type=OperationType.ASSERTION_CONFIRM,
                scope=OperationScope(
                    tenant_id=self.tenant_id,
                    matter_id=assertion.matter_id,
                    client_id=assertion.client_id,
                ),
                actor_id=request.by,
                authorization_context={"service_access": "review", "reviewer": request.by},
                correlation_id=assertion.audit_correlation_id or f"dependency_assertion:{assertion.id}",
                causation_id=assertion.id,
                idempotency_key=(
                    f"assertion-confirm:{assertion.id}:{assertion.state_version}"
                    if idempotency_suffix is None
                    else f"assertion-confirm:{assertion.id}:{assertion.state_version}:{idempotency_suffix}"
                ),
                source_resource_id=assertion.source_document_id,
                source_version=assertion.source_document_version,
                target_resource_id=assertion.suggested_edge.target_id,
                assertion_id=assertion.id,
                requested_transition="confirmed",
                payload={"expected_state_version": assertion.state_version},
            )
        )
        self._failure_injector.hit("after_authoritative_write_before_schedule")
        for _ in range(100):
            current = self.operation_store.get(operation.id)
            if current.status is OperationStatus.COMPLETED:
                confirmed = self._assertion_lifecycle.get(
                    assertion.id,
                    matter_id=assertion.matter_id,
                    client_id=assertion.client_id,
                )
                return confirmed.suggested_edge
            if current.status in {OperationStatus.TERMINAL_FAILED, OperationStatus.OPERATOR_REQUIRED}:
                raise BadRequestError("dependency assertion confirmation requires operational intervention")
            processed = self._operation_runner.run_once(worker_id="inline:assertion-confirmation")
            if processed is None:
                sleep(0.01)
            elif processed.id == operation.id and processed.status is OperationStatus.RETRYING:
                break
        raise BadRequestError("dependency assertion confirmation is durably queued for retry")

    def repair_confirmed_assertion_edge(
        self,
        assertion_id: str,
        *,
        matter_id: str,
        client_id: str,
    ) -> DependencyEdge:
        """Re-project one already-confirmed assertion only after its evidence lineage is reconstructed."""

        assertion = self._assertion_lifecycle.get(assertion_id, matter_id=matter_id, client_id=client_id)
        if assertion.decision is not SuggestionDecision.CONFIRMED:
            raise BadRequestError("only a confirmed assertion can repair a missing graph edge")
        if assertion.source_document_id is None:
            raise BadRequestError("confirmed assertion has no reconstructible source document")
        try:
            source = self.document_store.get_document(assertion.source_document_id)
        except Exception as exc:
            raise BadRequestError("confirmed assertion source document cannot be reconstructed") from exc
        if (
            source.version != assertion.source_document_version
            or source.content_sha256 != assertion.source_document_sha256
        ):
            raise BadRequestError("confirmed assertion source document provenance is invalid")
        result = self._schedule_assertion_confirmation(
            assertion,
            DependencyAssertionDecisionRequest(
                by="system:consistency-repair",
                decision="confirmed",
                matter_id=matter_id,
                client_id=client_id,
            ),
            idempotency_suffix=f"repair:{assertion.suggested_edge.id}",
        )
        if result.source_suggestion_id != assertion.id:
            raise BadRequestError("repaired graph edge has invalid assertion provenance")
        return result

    def _dispatch_operation(self, operation: OperationRecord, worker_id: str) -> OperationRecord:
        if operation.operation_type in {OperationType.ASSERTION_CREATE, OperationType.ASSERTION_TRANSITION}:
            return AssertionAuditProjection(
                lifecycle=self._assertion_lifecycle,
                operation_store=self.operation_store,
                failure_injector=self._failure_injector,
            ).apply(operation, worker_id)
        if operation.operation_type is OperationType.EVIDENCE_INGESTION:
            return EvidenceIngestionProjection(
                document_store=self.document_store,
                audit=self.audit,
                operation_store=self.operation_store,
                failure_injector=self._failure_injector,
            ).apply(operation, worker_id)
        if operation.operation_type is OperationType.SUGGESTION_GENERATION:
            return SuggestionGenerationProjection(
                authority_service=self,
                operation_store=self.operation_store,
                failure_injector=self._failure_injector,
            ).apply(operation, worker_id)
        if operation.operation_type is OperationType.AUTHORITY_CHANGE_PROPAGATION:
            return AuthorityChangeProjection(
                authority_service=self,
                operation_store=self.operation_store,
                failure_injector=self._failure_injector,
            ).apply(operation, worker_id)
        if operation.operation_type is OperationType.ASSERTION_CONFIRM:
            return AssertionConfirmationProjection(
                lifecycle=self._assertion_lifecycle,
                operation_store=self.operation_store,
                failure_injector=self._failure_injector,
            ).apply(operation, worker_id)
        if operation.operation_type is OperationType.SOURCE_REVISION_REVERIFY:
            return SourceRevisionReverificationProjection(
                lifecycle=self._assertion_lifecycle,
                operation_store=self.operation_store,
                failure_injector=self._failure_injector,
            ).apply(operation, worker_id)
        raise OperationRequiresIntervention(f"unsupported operation type: {operation.operation_type.value}")

    def evaluate_currency(self, item_id: str, *, as_of: datetime | None = None) -> dict[str, Any]:
        return self.currency_cache.get_or_evaluate(self._get_item(item_id), as_of=as_of).model_dump(mode="json")

    def record_verification(self, item_id: str, request: VerificationRequest) -> KnowledgeItem:
        if not request.basis and not request.source_ref:
            raise BadRequestError("verification basis or source_ref is required")
        item = self._get_item(item_id)
        from solomon.api import service as service_module

        if latest_verification_event(item) is None:
            item = self._append_lifecycle_event(
                item,
                VerificationLifecycleEvent(
                    item_id=item_id,
                    state=VerificationLifecycleState.IN_REVIEW,
                    actor_id=request.by,
                    reviewer_id=request.by,
                    occurred_at=request.recorded_at or datetime.now(timezone.utc),
                    basis="implicit review started by completion",
                    policy_version=self.verification_policy_version,
                    credence_policy_version=self.credence_policy_version,
                    policy_snapshot=self._policy_snapshot(),
                ),
                event_type="verification_lifecycle_in_review",
            )
        recorded = service_module.record_verification(
            item,
            by=request.by,
            outcome=request.outcome,
            successor_id=request.successor_id,
            recorded_at=request.recorded_at,
        )
        event = VerificationLifecycleEvent(
            item_id=item_id,
            state=lifecycle_state_for_outcome(request.outcome.value),
            actor_id=request.by,
            reviewer_id=request.by,
            occurred_at=recorded.recorded_at,
            basis=request.basis,
            source_ref=request.source_ref,
            policy_version=self.verification_policy_version,
            credence_policy_version=self.credence_policy_version,
            policy_snapshot=self._policy_snapshot(),
        )
        updated = append_verification_event(recorded.item, event)
        self.store.update_item(updated, event_type="verification_lifecycle_completed", occurred_at=recorded.recorded_at)
        self.index.upsert_item(updated)
        self.audit.log_verification_lifecycle(event)
        self.currency_cache.invalidate({item_id})
        if self.attestation_key is not None:
            attestation = sign_verification_attestation(
                updated,
                verified_by=request.by,
                outcome=request.outcome.value,
                signing_key=self.attestation_key,
            )
            self.audit.log_verification_attestation(attestation)
        return updated

    def assign_verification(self, item_id: str, request: VerificationAssignmentRequest) -> KnowledgeItem:
        item = self._get_item(item_id)
        timestamp = request.assigned_at or datetime.now(timezone.utc)
        event = VerificationLifecycleEvent(
            item_id=item_id,
            state=VerificationLifecycleState.ASSIGNED,
            actor_id=request.assigned_by,
            reviewer_id=request.reviewer_id,
            role=request.role,
            occurred_at=timestamp,
            basis=request.basis,
            source_ref=request.source_ref,
            policy_version=self.verification_policy_version,
            credence_policy_version=self.credence_policy_version,
            policy_snapshot=self._policy_snapshot(),
        )
        updated = append_verification_event(
            item.model_copy(update={"verified_state": VerifiedState.NEEDS_REVIEW}),
            event,
        )
        return self._write_lifecycle_update(updated, event, event_type="verification_lifecycle_assigned")

    def start_verification_review(self, item_id: str, request: VerificationReviewRequest) -> KnowledgeItem:
        item = self._get_item(item_id)
        timestamp = request.started_at or datetime.now(timezone.utc)
        event = VerificationLifecycleEvent(
            item_id=item_id,
            state=VerificationLifecycleState.IN_REVIEW,
            actor_id=request.reviewer_id,
            reviewer_id=request.reviewer_id,
            occurred_at=timestamp,
            basis=request.basis,
            source_ref=request.source_ref,
            policy_version=self.verification_policy_version,
            credence_policy_version=self.credence_policy_version,
            policy_snapshot=self._policy_snapshot(),
        )
        updated = append_verification_event(item, event)
        return self._write_lifecycle_update(updated, event, event_type="verification_lifecycle_in_review")

    def verification_queue(
        self,
        *,
        reviewer_id: str | None = None,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in self.store.get_many(matter_id=matter_id, client_id=client_id):
            currency = self.evaluate_currency(item.id)
            history = verification_history(item)
            latest = history[-1] if history else None
            assigned_reviewer = item.metadata.get("verification_reviewer_id")
            if reviewer_id is not None and assigned_reviewer != reviewer_id:
                continue
            needs_review = (
                str(currency.get("currency_state")) == CurrencyState.STALE_PENDING_REVERIFICATION.value
                or item.verified_state is VerifiedState.NEEDS_REVIEW
                or bool(item.metadata.get("staleness_reasons"))
            )
            if not needs_review:
                continue
            rows.append(
                {
                    "item": item.model_dump(mode="json"),
                    "currency": currency,
                    "reviewer_id": assigned_reviewer,
                    "verification_status": item.metadata.get("verification_status"),
                    "latest_event": latest.model_dump(mode="json") if latest else None,
                    "history": [event.model_dump(mode="json") for event in history],
                }
            )
        return sorted(rows, key=lambda row: (str(row.get("reviewer_id") or ""), str(row["item"]["id"])))

    def register_authority_change(
        self,
        authority_id: str,
        request: AuthorityChangeRequest,
        *,
        change_id: str | None = None,
    ) -> dict[str, Any]:
        idempotency_key = change_id or f"{authority_id}:{request.new_version}:{request.changed_at}"
        self._failure_injector.hit("before_authoritative_write")
        operation, _ = self.operation_store.create(
            OperationRecord(
                operation_type=OperationType.AUTHORITY_CHANGE_PROPAGATION,
                scope=OperationScope(tenant_id=self.tenant_id),
                actor_id="system:authority-monitor",
                authorization_context={"service_access": "curate", "actor_type": "system"},
                correlation_id=f"authority_event:{change_id or idempotency_key}",
                causation_id=change_id,
                idempotency_key=f"authority-change:{idempotency_key}",
                source_resource_id=authority_id,
                target_resource_id=authority_id,
                requested_transition="authority_changed",
                payload={
                    "new_version": request.new_version,
                    "changed_at": request.changed_at,
                    "change_id": change_id,
                },
            )
        )
        self._failure_injector.hit("after_authoritative_write_before_schedule")
        for _ in range(100):
            current = self.operation_store.get(operation.id)
            if current.status is OperationStatus.COMPLETED:
                impact = CurrencyPropagator(graph=self.graph, store=self.store).impact_query(authority_id)
                result_change_id = change_id or operation.id
                return impact.model_copy(update={"change_id": result_change_id}).model_dump(mode="json")
            if current.status in {OperationStatus.TERMINAL_FAILED, OperationStatus.OPERATOR_REQUIRED}:
                raise BadRequestError("authority change propagation requires operational intervention")
            processed = self._operation_runner.run_once(worker_id="inline:authority-change")
            if processed is None:
                sleep(0.01)
            elif processed.id == operation.id and processed.status is OperationStatus.RETRYING:
                break
        raise BadRequestError("authority change propagation is durably queued for retry")

    def add_dependency(self, request: DependencyRequest) -> DependencyEdge:
        edge = DependencyEdge(
            source_id=request.source_id,
            target_id=request.target_id,
            edge_type=request.edge_type,
            target_kind=request.target_kind,  # type: ignore[arg-type]
            confidence=request.confidence,
            created_by=request.created_by,
            reason=request.reason,
        )
        edge = self.graph.add_dependency(edge)
        self._detect_for_edge(edge)
        return edge

    def suggest_dependencies(
        self,
        request: DependencySuggestionRequest,
        *,
        router: ModelRouter | None = None,
    ) -> list[DependencySuggestion]:
        item = self._get_item(request.item_id)
        return self._create_dependency_suggestions(
            item,
            use_llm=request.use_llm,
            router=router,
        )

    def dependency_suggestions(
        self,
        *,
        item_id: str | None = None,
        decision: SuggestionDecision | None = None,
        limit: int = 100,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> list[DependencySuggestion]:
        return self._dependency_lifecycle.list(
            item_id=item_id,
            decision=decision,
            limit=limit,
            matter_id=matter_id,
            client_id=client_id,
        )

    def confirm_dependency_suggestion(
        self,
        suggestion_id: str,
        request: DependencySuggestionDecisionRequest,
    ) -> DependencyEdge:
        return self._dependency_lifecycle.confirm(suggestion_id, request)

    def reject_dependency_suggestion(
        self,
        suggestion_id: str,
        request: DependencySuggestionDecisionRequest,
    ) -> DependencySuggestion:
        return self._dependency_lifecycle.reject(suggestion_id, request)

    def defer_dependency_suggestion(
        self,
        suggestion_id: str,
        request: DependencySuggestionDecisionRequest,
    ) -> DependencySuggestion:
        return self._dependency_lifecycle.defer(suggestion_id, request)

    def create_dependency_assertion(self, request: DependencyAssertionCreateRequest) -> DependencySuggestion:
        return self._assertion_lifecycle.create(request)

    def dependency_assertions(self, **filters: Any) -> list[DependencySuggestion]:
        return self._assertion_lifecycle.list_assertions(**filters)

    def get_dependency_assertion(
        self,
        assertion_id: str,
        *,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> DependencySuggestion:
        return self._assertion_lifecycle.get(assertion_id, matter_id=matter_id, client_id=client_id)

    def decide_dependency_assertion(
        self,
        assertion_id: str,
        request: DependencyAssertionDecisionRequest,
    ) -> DependencySuggestion | DependencyEdge:
        return self._assertion_lifecycle.decide(assertion_id, request)

    def withdraw_dependency_assertion(
        self,
        assertion_id: str,
        request: DependencyAssertionWithdrawRequest,
    ) -> DependencySuggestion:
        return self._assertion_lifecycle.withdraw(assertion_id, request)

    def dependency_assertion_history(
        self,
        assertion_id: str,
        *,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        return self._assertion_lifecycle.history(assertion_id, matter_id=matter_id, client_id=client_id)

    def record_source_document_ingestion(self, document: Any, *, candidate_count: int) -> OperationRecord:
        """Durably schedule the audit projection for a SQLite-authoritative source document."""

        operation, _ = self._create_evidence_ingestion_operation(document, candidate_count=candidate_count)
        self._failure_injector.hit("after_evidence_authoritative_write_before_schedule")
        for _ in range(100):
            current = self.operation_store.get(operation.id)
            if current.status is OperationStatus.COMPLETED:
                return cast(OperationRecord, current)
            if current.status in {OperationStatus.TERMINAL_FAILED, OperationStatus.OPERATOR_REQUIRED}:
                raise BadRequestError("source document audit projection requires operational intervention")
            processed = self._operation_runner.run_once(worker_id="inline:evidence-ingestion")
            if processed is None:
                sleep(0.01)
            elif processed.id == operation.id and processed.status is OperationStatus.RETRYING:
                break
        raise BadRequestError("source document audit projection is durably queued for retry")

    def record_suggestion_generation(self, item: KnowledgeItem) -> OperationRecord:
        """Durably schedule deterministic, review-only suggestion generation for one knowledge item."""

        operation, _ = self._create_suggestion_generation_operation(item)
        self._failure_injector.hit("after_suggestion_authoritative_write_before_schedule")
        for _ in range(100):
            current = self.operation_store.get(operation.id)
            if current.status is OperationStatus.COMPLETED:
                return cast(OperationRecord, current)
            if current.status in {OperationStatus.TERMINAL_FAILED, OperationStatus.OPERATOR_REQUIRED}:
                raise BadRequestError("dependency suggestion generation requires operational intervention")
            processed = self._operation_runner.run_once(worker_id="inline:suggestion-generation")
            if processed is None:
                sleep(0.01)
            elif processed.id == operation.id and processed.status is OperationStatus.RETRYING:
                break
        raise BadRequestError("dependency suggestion generation is durably queued for retry")

    def record_assertion_creation(self, assertion: DependencySuggestion) -> DependencySuggestion:
        self._record_assertion_audit_operation(assertion, operation_type=OperationType.ASSERTION_CREATE)
        return self._assertion_lifecycle.get(
            assertion.id,
            matter_id=assertion.matter_id,
            client_id=assertion.client_id,
        )

    def record_assertion_transition(self, assertion: DependencySuggestion) -> DependencySuggestion:
        self._record_assertion_audit_operation(assertion, operation_type=OperationType.ASSERTION_TRANSITION)
        return self._assertion_lifecycle.get(
            assertion.id,
            matter_id=assertion.matter_id,
            client_id=assertion.client_id,
        )

    def _record_assertion_audit_operation(
        self,
        assertion: DependencySuggestion,
        *,
        operation_type: OperationType,
    ) -> OperationRecord:
        operation, _ = cast(
            tuple[OperationRecord, bool],
            self.operation_store.create(
                self._assertion_audit_record(assertion, operation_type=operation_type)
            ),
        )
        self._failure_injector.hit("after_assertion_audit_authoritative_write_before_schedule")
        for _ in range(100):
            current = self.operation_store.get(operation.id)
            if current.status is OperationStatus.COMPLETED:
                return cast(OperationRecord, current)
            if current.status in {OperationStatus.TERMINAL_FAILED, OperationStatus.OPERATOR_REQUIRED}:
                raise BadRequestError("dependency assertion audit projection requires operational intervention")
            processed = self._operation_runner.run_once(worker_id="inline:assertion-audit")
            if processed is None:
                sleep(0.01)
            elif processed.id == operation.id and processed.status is OperationStatus.RETRYING:
                break
        raise BadRequestError("dependency assertion audit projection is durably queued for retry")

    def mark_dependency_assertions_for_source_revision(
        self,
        *,
        previous_document_id: str | None,
        replacement_document_id: str,
    ) -> list[DependencySuggestion]:
        if previous_document_id is None:
            return []
        updated: list[DependencySuggestion] = []
        for assertion in self._assertion_lifecycle.list_assertions(limit=10_000):
            if assertion.source_document_id != previous_document_id or assertion.needs_reverification:
                continue
            operation, _ = self._create_source_revision_operation(assertion, replacement_document_id)
            self._failure_injector.hit("after_authoritative_write_before_schedule")
            for _ in range(100):
                current = self.operation_store.get(operation.id)
                if current.status is OperationStatus.COMPLETED:
                    updated.append(
                        self._assertion_lifecycle.get(
                            assertion.id,
                            matter_id=assertion.matter_id,
                            client_id=assertion.client_id,
                        )
                    )
                    break
                if current.status in {OperationStatus.TERMINAL_FAILED, OperationStatus.OPERATOR_REQUIRED}:
                    raise BadRequestError("source revision reverification requires operational intervention")
                processed = self._operation_runner.run_once(worker_id="inline:source-revision")
                if processed is None:
                    sleep(0.01)
                elif processed.id == operation.id and processed.status is OperationStatus.RETRYING:
                    raise BadRequestError("source revision reverification is durably queued for retry")
            else:
                raise BadRequestError("source revision reverification is durably queued for retry")
        return updated

    def reconcile_source_revisions(self) -> int:
        """Schedule missing source-version projections found after an interruption before journal creation."""

        created = 0
        for assertion in self._assertion_lifecycle.list_assertions(limit=10_000):
            if assertion.needs_reverification or assertion.source_document_id is None:
                continue
            try:
                source = self.document_store.get_document(assertion.source_document_id)
            except SourceDocumentNotFoundError:
                continue
            for replacement in self.document_store.list_documents(source.source_id):
                if replacement.previous_version_id != source.id:
                    continue
                _, scheduled = self._create_source_revision_operation(assertion, replacement.id)
                created += int(scheduled)
        return created

    def reconcile_evidence_ingestions(self) -> int:
        """Discover source documents written before their durable audit operation was created."""

        known_documents = {
            operation.target_resource_id
            for operation in self.operation_store.list(limit=10_000)
            if operation.operation_type is OperationType.EVIDENCE_INGESTION
        }
        created = 0
        for source in self.document_store.list_sources():
            for document in self.document_store.list_documents(source.id):
                if document.id in known_documents:
                    continue
                _, scheduled = self._create_evidence_ingestion_operation(
                    document,
                    candidate_count=len(self.document_store.list_candidates(document.id)),
                )
                created += int(scheduled)
        return created

    def reconcile_suggestion_generations(self) -> int:
        """Discover knowledge items written before their review-only suggestion operation was created."""

        known_items = {
            operation.target_resource_id
            for operation in self.operation_store.list(limit=10_000)
            if operation.operation_type is OperationType.SUGGESTION_GENERATION
        }
        created = 0
        for item in self.store.get_many():
            if item.id in known_items:
                continue
            _, scheduled = self._create_suggestion_generation_operation(item)
            created += int(scheduled)
        return created

    def reconcile_assertion_audits(self) -> int:
        """Schedule missing creation or non-confirming assertion audit projections after interruption."""

        created = 0
        for assertion in self._assertion_lifecycle.list_assertions(limit=10_000):
            if assertion.creation_audit_id is None:
                _, scheduled = self.operation_store.create(
                    self._assertion_audit_record(assertion, operation_type=OperationType.ASSERTION_CREATE)
                )
                created += int(scheduled)
            if assertion.decision in {
                SuggestionDecision.REJECTED,
                SuggestionDecision.DEFERRED,
                SuggestionDecision.WITHDRAWN,
            }:
                _, scheduled = self.operation_store.create(
                    self._assertion_audit_record(assertion, operation_type=OperationType.ASSERTION_TRANSITION)
                )
                created += int(scheduled)
        return created

    def _create_evidence_ingestion_operation(
        self,
        document: Any,
        *,
        candidate_count: int,
    ) -> tuple[OperationRecord, bool]:
        return cast(
            tuple[OperationRecord, bool],
            self.operation_store.create(
                OperationRecord(
                    operation_type=OperationType.EVIDENCE_INGESTION,
                    scope=OperationScope(tenant_id=self.tenant_id),
                    actor_id="system:source-ingestion",
                    authorization_context={"service_access": "curate", "actor_type": "system"},
                    correlation_id=f"source_document:{document.id}",
                    causation_id=document.id,
                    idempotency_key=f"evidence-ingestion:{document.id}",
                    source_resource_id=document.source_id,
                    source_version=document.version,
                    target_resource_id=document.id,
                    requested_transition="audit_recorded",
                    payload={"candidate_count": candidate_count},
                )
            ),
        )

    def _create_suggestion_generation_operation(self, item: KnowledgeItem) -> tuple[OperationRecord, bool]:
        return cast(
            tuple[OperationRecord, bool],
            self.operation_store.create(
                OperationRecord(
                    operation_type=OperationType.SUGGESTION_GENERATION,
                    scope=OperationScope(
                        tenant_id=self.tenant_id,
                        matter_id=item.matter_id,
                        client_id=item.client_id,
                    ),
                    actor_id="system:suggestion-generation",
                    authorization_context={"service_access": "curate", "actor_type": "system"},
                    correlation_id=f"knowledge_item:{item.id}",
                    causation_id=item.id,
                    idempotency_key=f"suggestion-generation:{item.id}",
                    target_resource_id=item.id,
                    requested_transition="suggestions_generated",
                )
            ),
        )

    def _assertion_audit_record(
        self,
        assertion: DependencySuggestion,
        *,
        operation_type: OperationType,
    ) -> OperationRecord:
        transition = "created" if operation_type is OperationType.ASSERTION_CREATE else assertion.decision.value
        return OperationRecord(
            operation_type=operation_type,
            scope=OperationScope(
                tenant_id=self.tenant_id,
                matter_id=assertion.matter_id,
                client_id=assertion.client_id,
            ),
            actor_id=assertion.decided_by or assertion.created_by or "system:assertion-audit",
            authorization_context={"service_access": "review", "actor_type": "assertion"},
            correlation_id=assertion.audit_correlation_id or f"dependency_assertion:{assertion.id}",
            causation_id=assertion.id,
            idempotency_key=f"{operation_type.value}:{assertion.id}:{assertion.state_version}",
            source_resource_id=assertion.source_document_id,
            source_version=assertion.source_document_version,
            target_resource_id=assertion.suggested_edge.target_id,
            assertion_id=assertion.id,
            requested_transition=transition,
            payload={"expected_state_version": assertion.state_version},
        )

    def _create_source_revision_operation(
        self,
        assertion: DependencySuggestion,
        replacement_document_id: str,
    ) -> tuple[OperationRecord, bool]:
        if assertion.source_document_id is None:
            raise BadRequestError("source revision operation requires an assertion source document")
        return cast(
            tuple[OperationRecord, bool],
            self.operation_store.create(
                OperationRecord(
                    operation_type=OperationType.SOURCE_REVISION_REVERIFY,
                    scope=OperationScope(
                        tenant_id=self.tenant_id,
                        matter_id=assertion.matter_id,
                        client_id=assertion.client_id,
                    ),
                    actor_id="system:source-revision",
                    authorization_context={"service_access": "curate", "actor_type": "system"},
                    correlation_id=assertion.audit_correlation_id or f"dependency_assertion:{assertion.id}",
                    causation_id=assertion.id,
                    idempotency_key=f"source-revision:{assertion.id}:{replacement_document_id}",
                    source_resource_id=assertion.source_document_id,
                    source_version=assertion.source_document_version,
                    target_resource_id=replacement_document_id,
                    assertion_id=assertion.id,
                    requested_transition="needs_reverification",
                )
            ),
        )

    def impact_query(self, authority_id: str, *, as_of: datetime | None = None) -> dict[str, Any]:
        timestamp = as_of or self._deterministic_store_timestamp()
        return (
            CurrencyPropagator(graph=self.graph, store=self.store)
            .impact_query(
                authority_id,
                as_of=timestamp,
            )
            .model_dump(mode="json")
        )

    def dependency_graph(
        self,
        *,
        output_format: GraphFormat = "mermaid",
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> str:
        view = dependency_graph_view(graph=self.graph, store=self.store, matter_id=matter_id, client_id=client_id)
        return render_dependency_graph(view, output_format=output_format)

    def extract_references(self, request: ReferenceExtractionRequest) -> ReferenceExtraction:
        return extract_defined_terms_and_citations(content=request.content)

    def predict_staleness(self, request: StalenessPredictionRequest) -> StalenessRiskReport:
        return predict_staleness_risk(
            request.pending_amendments,
            graph=self.graph,
            store=self.store,
            as_of=parse_iso_datetime(request.as_of) if request.as_of else None,
            lookahead_days=request.lookahead_days,
        )

    def _create_dependency_suggestions(
        self,
        item: KnowledgeItem,
        *,
        use_llm: bool = False,
        router: ModelRouter | None = None,
    ) -> list[DependencySuggestion]:
        if item.content_role is KnowledgeContentRole.INSTRUCTION:
            return []
        suggestions = suggest_authority_dependencies(
            item_id=item.id,
            content=item.content,
            boundary=self.boundary,
            matter_id=item.matter_id,
            client_id=item.client_id,
            source_document_id=source_document_value(item, "id"),
            source_document_version=source_document_version(item),
            previous_source_document_id=source_document_value(item, "previous_document_id"),
            source_offset=source_document_offset(item),
            audit_correlation_id=f"dependency_suggestion:{item.id}",
        )
        if use_llm:
            if router is None:
                raise BadRequestError("LLM dependency suggestion requires a model router")
            suggestions.extend(
                suggest_authority_dependencies_with_llm(
                    item_id=item.id,
                    content=item.content,
                    boundary=self.boundary,
                    router=router,
                    matter_id=item.matter_id,
                )
            )
        stored: list[DependencySuggestion] = []
        existing_edges = {
            (edge.target_id, edge.edge_type) for edge in self.graph.get_dependencies(item.id) if edge.valid_to is None
        }
        existing_suggestions = {
            (suggestion.suggested_edge.target_id, suggestion.suggested_edge.edge_type)
            for suggestion in self.graph.list_dependency_suggestions(item_id=item.id)
        }
        for suggestion in suggestions:
            key = (suggestion.suggested_edge.target_id, suggestion.suggested_edge.edge_type)
            if key in existing_edges or key in existing_suggestions:
                continue
            stored_suggestion = self.graph.add_dependency_suggestion(suggestion)
            existing_suggestions.add(key)
            stored.append(stored_suggestion)
            self.audit.append(
                "dependency_suggestion_created",
                {
                    "suggestion_id": stored_suggestion.id,
                    "item_id": stored_suggestion.item_id,
                    "target_id": stored_suggestion.suggested_edge.target_id,
                    "edge_type": stored_suggestion.suggested_edge.edge_type.value,
                    "source": stored_suggestion.source,
                    "fingerprint": stored_suggestion.fingerprint,
                    "source_document_id": stored_suggestion.source_document_id,
                    "source_document_version": stored_suggestion.source_document_version,
                    "source_span": [stored_suggestion.source_span_start, stored_suggestion.source_span_end],
                    "authority_span": [stored_suggestion.authority_span_start, stored_suggestion.authority_span_end],
                    "authority_ref_sha256": digest(stored_suggestion.authority_ref),
                },
                attribution=AuditAttribution(
                    actor_id="system:dependency-extraction",
                    correlation_id=stored_suggestion.audit_correlation_id,
                ),
            )
        return stored

    def detect_contradictions(
        self,
        *,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> list[ContradictionSignal]:
        signals = detect_same_authority_opposite_conclusions(
            store=self.store,
            graph=self.graph,
            matter_id=matter_id,
            client_id=client_id,
        )
        applied: list[ContradictionSignal] = []
        for signal in signals:
            item = self._get_item(signal.item_id)
            if any(existing.signal_id == signal.signal_id for existing in contradictions_for_item(item)):
                continue
            updated = append_contradiction_signal(item, signal)
            event = VerificationLifecycleEvent(
                item_id=item.id,
                state=VerificationLifecycleState.REQUESTED,
                actor_id="system",
                occurred_at=signal.detected_at,
                basis=signal.basis,
                source_ref=signal.authority_id,
                policy_version=self.verification_policy_version,
                credence_policy_version=self.credence_policy_version,
                policy_snapshot=self._policy_snapshot(),
            )
            updated = append_verification_event(updated, event)
            self.store.update_item(
                updated,
                event_type="knowledge_item_contradiction_flagged",
                occurred_at=signal.detected_at,
            )
            self.index.upsert_item(updated)
            self.currency_cache.invalidate({item.id})
            self.audit.log_contradiction_signal(signal)
            self.audit.log_verification_lifecycle(event)
            applied.append(signal)
        return applied

    def _append_lifecycle_event(
        self,
        item: KnowledgeItem,
        event: VerificationLifecycleEvent,
        *,
        event_type: str,
    ) -> KnowledgeItem:
        updated = append_verification_event(item, event)
        return self._write_lifecycle_update(updated, event, event_type=event_type)

    def _write_lifecycle_update(
        self,
        item: KnowledgeItem,
        event: VerificationLifecycleEvent,
        *,
        event_type: str,
    ) -> KnowledgeItem:
        self.store.update_item(item, event_type=event_type, occurred_at=event.occurred_at)
        self.index.upsert_item(item)
        self.currency_cache.invalidate({item.id})
        self.audit.log_verification_lifecycle(event)
        return item

    def _detect_for_edge(self, edge: DependencyEdge) -> None:
        if edge.edge_type is not EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL:
            return
        try:
            item = self._get_item(edge.source_id)
        except NotFoundError:
            return
        self.detect_contradictions(matter_id=item.matter_id, client_id=item.client_id)

    def _policy_snapshot(self) -> dict[str, Any]:
        return {
            "verification_policy": self.currency_cache.policy.model_dump(mode="json"),
            "verification_policy_version": self.verification_policy_version,
            "credence_policy": self.credence.policy.model_dump(mode="json"),
            "credence_policy_version": self.credence_policy_version,
        }
