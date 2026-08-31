# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any, cast

from solomon.audit.journal import AuditAttribution
from solomon.graph.suggestions import DependencySuggestion
from solomon.operations.execution import OperationRequiresIntervention
from solomon.operations.failure_injection import OperationFailureInjector
from solomon.operations.models import OperationPhase, OperationRecord, OperationStatus, OperationType


class SourceRevisionReverificationProjection:
    """Project one reconstructible source revision into one governed assertion re-verification marker."""

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
        if operation.operation_type is not OperationType.SOURCE_REVISION_REVERIFY:
            raise OperationRequiresIntervention("operation type is not source revision reverification")
        if operation.status is not OperationStatus.CLAIMED or operation.assertion_id is None:
            raise OperationRequiresIntervention("source revision operation is incomplete or not claimed")
        if operation.source_resource_id is None or operation.target_resource_id is None:
            raise OperationRequiresIntervention("source revision operation has no document lineage")
        assertion = self._lifecycle.get(
            operation.assertion_id,
            matter_id=operation.scope.matter_id,
            client_id=operation.scope.client_id,
        )
        self._validate(operation, assertion)
        current = operation
        if current.last_successful_checkpoint not in {OperationPhase.GRAPH, OperationPhase.AUDIT}:
            self._failure_injector.hit("during_source_revision_reverification")
            if not assertion.needs_reverification:
                assertion = assertion.model_copy(
                    update={"needs_reverification": True, "state_version": assertion.state_version + 1}
                )
                self._lifecycle._graph.update_dependency_suggestion(assertion)
            current = self._operation_store.checkpoint(
                current.id,
                worker_id=worker_id,
                phase=OperationPhase.GRAPH,
                result_entity_id=assertion.id,
                result_edge_id=assertion.suggested_edge.id if assertion.decision.value == "confirmed" else None,
            )

        if current.last_successful_checkpoint is not OperationPhase.AUDIT:
            entry = self._lifecycle._audit.append_idempotent(
                "dependency_assertion_reverification_requested",
                {
                    "assertion_id": assertion.id,
                    "source_document_id": operation.source_resource_id,
                    "replacement_document_id": operation.target_resource_id,
                    "edge_id": assertion.suggested_edge.id if assertion.decision.value == "confirmed" else None,
                },
                operation_id=f"{current.id}:reverification",
                attribution=AuditAttribution(
                    actor_id="system:source-revision",
                    correlation_id=operation.correlation_id,
                ),
            )
            if assertion.reverification_audit_id != entry.entry_hash:
                assertion = assertion.model_copy(update={"reverification_audit_id": entry.entry_hash})
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
            self._operation_store.complete(
                current.id,
                worker_id=worker_id,
                result_entity_id=assertion.id,
                result_edge_id=assertion.suggested_edge.id if assertion.decision.value == "confirmed" else None,
            ),
        )

    def _validate(self, operation: OperationRecord, assertion: DependencySuggestion) -> None:
        if assertion.matter_id != operation.scope.matter_id or assertion.client_id != operation.scope.client_id:
            raise OperationRequiresIntervention("assertion scope does not match source revision operation")
        if assertion.source_document_id != operation.source_resource_id:
            raise OperationRequiresIntervention("assertion is not bound to the revised source version")
        try:
            replacement = self._lifecycle._document_store.get_document(operation.target_resource_id)
        except Exception as exc:
            raise OperationRequiresIntervention("replacement source version cannot be reconstructed") from exc
        if replacement.previous_version_id != operation.source_resource_id:
            raise OperationRequiresIntervention("replacement does not continue the source version lineage")


__all__ = ["SourceRevisionReverificationProjection"]
