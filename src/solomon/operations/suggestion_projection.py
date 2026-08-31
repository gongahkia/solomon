# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any, cast

from solomon.audit.journal import AuditAttribution
from solomon.operations.execution import OperationRequiresIntervention
from solomon.operations.failure_injection import OperationFailureInjector
from solomon.operations.models import OperationPhase, OperationRecord, OperationStatus, OperationType


class SuggestionGenerationProjection:
    """Generate deterministic, review-only suggestions once for an authoritative knowledge item."""

    def __init__(
        self,
        *,
        authority_service: Any,
        operation_store: Any,
        failure_injector: OperationFailureInjector | None = None,
    ) -> None:
        self._authority_service = authority_service
        self._operation_store = operation_store
        self._failure_injector = failure_injector or OperationFailureInjector()

    def apply(self, operation: OperationRecord, worker_id: str) -> OperationRecord:
        if operation.operation_type is not OperationType.SUGGESTION_GENERATION:
            raise OperationRequiresIntervention("operation type is not suggestion generation")
        if operation.status is not OperationStatus.CLAIMED or operation.target_resource_id is None:
            raise OperationRequiresIntervention("suggestion generation operation is incomplete or not claimed")
        item = self._authority_service._get_item(operation.target_resource_id)
        if item.matter_id != operation.scope.matter_id or item.client_id != operation.scope.client_id:
            raise OperationRequiresIntervention("knowledge item scope does not match immutable operation scope")
        current = operation
        suggestion_count = operation.payload.get("suggestion_count")
        if current.last_successful_checkpoint not in {OperationPhase.GRAPH, OperationPhase.AUDIT}:
            self._failure_injector.hit("during_suggestion_generation")
            suggestion_count = len(self._authority_service._create_dependency_suggestions(item))
            current = self._operation_store.checkpoint(
                current.id,
                worker_id=worker_id,
                phase=OperationPhase.GRAPH,
                result_entity_id=item.id,
            )
        if current.last_successful_checkpoint is not OperationPhase.AUDIT:
            self._failure_injector.hit("after_suggestions_before_audit")
            entry = self._authority_service.audit.append_idempotent(
                "dependency_suggestions_generated",
                {
                    "item_id": item.id,
                    "suggestion_count": suggestion_count if isinstance(suggestion_count, int) else 0,
                },
                operation_id=f"{current.id}:audit",
                attribution=AuditAttribution(actor_id=operation.actor_id, correlation_id=operation.correlation_id),
            )
            current = self._operation_store.checkpoint(
                current.id,
                worker_id=worker_id,
                phase=OperationPhase.AUDIT,
                result_entity_id=item.id,
                audit_entry_hash=entry.entry_hash,
            )
        return cast(
            OperationRecord,
            self._operation_store.complete(current.id, worker_id=worker_id, result_entity_id=item.id),
        )


__all__ = ["SuggestionGenerationProjection"]
