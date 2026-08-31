# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any, cast

from solomon.audit.journal import AuditAttribution
from solomon.graph.suggestions import SuggestionDecision
from solomon.operations.execution import OperationRequiresIntervention
from solomon.operations.failure_injection import OperationFailureInjector
from solomon.operations.models import OperationPhase, OperationRecord, OperationStatus, OperationType


class AssertionAuditProjection:
    """Replay an assertion creation or non-confirming transition audit without changing edge state."""

    def __init__(
        self,
        *,
        lifecycle: Any,
        operation_store: Any,
        failure_injector: OperationFailureInjector | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._operation_store = operation_store
        self._failure_injector = failure_injector or OperationFailureInjector()

    def apply(self, operation: OperationRecord, worker_id: str) -> OperationRecord:
        if operation.operation_type not in {OperationType.ASSERTION_CREATE, OperationType.ASSERTION_TRANSITION}:
            raise OperationRequiresIntervention("operation type is not an assertion audit projection")
        if operation.status is not OperationStatus.CLAIMED or operation.assertion_id is None:
            raise OperationRequiresIntervention("assertion audit operation is incomplete or not claimed")
        assertion = self._lifecycle.get(
            operation.assertion_id,
            matter_id=operation.scope.matter_id,
            client_id=operation.scope.client_id,
        )
        if assertion.matter_id != operation.scope.matter_id or assertion.client_id != operation.scope.client_id:
            raise OperationRequiresIntervention("assertion scope does not match immutable operation scope")
        event_type, audit_field = self._event_for(operation, assertion.decision)
        current = operation
        if current.last_successful_checkpoint is not OperationPhase.AUDIT:
            self._failure_injector.hit("during_assertion_audit_projection")
            from solomon.api.services.dependency_assertions import _assertion_audit_payload

            entry = self._lifecycle._audit.append_idempotent(
                event_type,
                _assertion_audit_payload(assertion),
                operation_id=f"{current.id}:audit",
                attribution=AuditAttribution(actor_id=operation.actor_id, correlation_id=operation.correlation_id),
            )
            if getattr(assertion, audit_field) is None:
                assertion = assertion.model_copy(update={audit_field: entry.entry_hash})
                self._lifecycle._graph.update_dependency_suggestion(assertion)
            current = self._operation_store.checkpoint(
                current.id,
                worker_id=worker_id,
                phase=OperationPhase.AUDIT,
                result_entity_id=assertion.id,
                audit_entry_hash=entry.entry_hash,
            )
        return cast(
            OperationRecord,
            self._operation_store.complete(current.id, worker_id=worker_id, result_entity_id=assertion.id),
        )

    @staticmethod
    def _event_for(operation: OperationRecord, decision: SuggestionDecision) -> tuple[str, str]:
        if operation.operation_type is OperationType.ASSERTION_CREATE:
            return "dependency_assertion_created", "creation_audit_id"
        if decision not in {SuggestionDecision.REJECTED, SuggestionDecision.DEFERRED, SuggestionDecision.WITHDRAWN}:
            raise OperationRequiresIntervention("assertion transition is not a terminal or deferred review outcome")
        if operation.requested_transition != decision.value:
            raise OperationRequiresIntervention("assertion transition does not match immutable operation request")
        return f"dependency_assertion_{decision.value}", "review_audit_id"


__all__ = ["AssertionAuditProjection"]
