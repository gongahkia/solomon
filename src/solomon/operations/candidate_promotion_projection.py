# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any, cast

from solomon.audit.journal import AuditAttribution
from solomon.currency.models import now_utc
from solomon.operations.execution import OperationRequiresIntervention
from solomon.operations.failure_injection import OperationFailureInjector
from solomon.operations.models import OperationPhase, OperationRecord, OperationStatus, OperationType
from solomon.sources.models import CandidateClaimStatus
from solomon.sources.store import CandidateClaimNotFoundError


class CandidatePromotionProjection:
    """Reconcile the SQLite candidate marker after its knowledge item is durable."""

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
        if operation.operation_type is not OperationType.CANDIDATE_PROMOTION:
            raise OperationRequiresIntervention("operation type is not candidate promotion")
        if (
            operation.status is not OperationStatus.CLAIMED
            or operation.source_resource_id is None
            or operation.target_resource_id is None
        ):
            raise OperationRequiresIntervention("candidate promotion operation is incomplete or not claimed")
        try:
            candidate = self._authority_service.document_store.get_candidate(operation.source_resource_id)
        except CandidateClaimNotFoundError as exc:
            raise OperationRequiresIntervention("candidate claim cannot be reconstructed") from exc
        item = self._authority_service._get_item(operation.target_resource_id)
        if item.matter_id != operation.scope.matter_id or item.client_id != operation.scope.client_id:
            raise OperationRequiresIntervention("knowledge item scope does not match immutable operation scope")
        if item.metadata.get("source_candidate_id") != candidate.id:
            raise OperationRequiresIntervention("knowledge item does not preserve immutable candidate provenance")
        current = operation
        if current.last_successful_checkpoint is not OperationPhase.AUDIT:
            self._failure_injector.hit("during_candidate_promotion_projection")
            if candidate.status is CandidateClaimStatus.PENDING:
                candidate = self._authority_service.document_store.update_candidate(
                    candidate.model_copy(
                        update={
                            "status": CandidateClaimStatus.PROMOTED,
                            "promotion_item_id": item.id,
                            "decision_by": operation.actor_id,
                            "decided_at": now_utc(),
                        }
                    )
                )
            elif candidate.status is not CandidateClaimStatus.PROMOTED or candidate.promotion_item_id != item.id:
                raise OperationRequiresIntervention("candidate claim is no longer safe to promote")
            self._failure_injector.hit("after_candidate_promotion_before_audit")
            entry = self._authority_service.audit.append_idempotent(
                "candidate_claim_promoted",
                {"candidate_id": candidate.id, "document_id": candidate.document_id, "item_id": item.id},
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


__all__ = ["CandidatePromotionProjection"]
