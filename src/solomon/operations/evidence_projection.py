# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
from typing import Any, cast

from solomon.audit.journal import AuditAttribution
from solomon.operations.execution import OperationRequiresIntervention
from solomon.operations.failure_injection import OperationFailureInjector
from solomon.operations.models import OperationPhase, OperationRecord, OperationStatus, OperationType
from solomon.sources.store import SourceDocumentNotFoundError


class EvidenceIngestionProjection:
    """Append the audit projection for one SQLite-authoritative source document exactly once."""

    def __init__(
        self,
        *,
        document_store: Any,
        audit: Any,
        operation_store: Any,
        failure_injector: OperationFailureInjector | None = None,
    ) -> None:
        self._document_store = document_store
        self._audit = audit
        self._operation_store = operation_store
        self._failure_injector = failure_injector or OperationFailureInjector()

    def apply(self, operation: OperationRecord, worker_id: str) -> OperationRecord:
        if operation.operation_type is not OperationType.EVIDENCE_INGESTION:
            raise OperationRequiresIntervention("operation type is not source evidence ingestion")
        if operation.status is not OperationStatus.CLAIMED or operation.target_resource_id is None:
            raise OperationRequiresIntervention("source evidence operation is incomplete or not claimed")
        try:
            document = self._document_store.get_document(operation.target_resource_id)
        except SourceDocumentNotFoundError as exc:
            raise OperationRequiresIntervention("source document cannot be reconstructed for audit projection") from exc
        if operation.source_resource_id != document.source_id:
            raise OperationRequiresIntervention("source document does not match immutable operation origin")
        current = operation
        if current.last_successful_checkpoint is not OperationPhase.AUDIT:
            self._failure_injector.hit("during_evidence_ingestion_projection")
            candidate_count = operation.payload.get("candidate_count")
            entry = self._audit.append_idempotent(
                "source_document_ingested",
                {
                    "source_id": document.source_id,
                    "document_id": document.id,
                    "external_id_sha256": hashlib.sha256(document.external_id.encode("utf-8")).hexdigest(),
                    "version": document.version,
                    "content_sha256": document.content_sha256,
                    "extraction_state": document.extraction_state.value,
                    "candidate_count": candidate_count if isinstance(candidate_count, int) else 0,
                },
                operation_id=f"{current.id}:audit",
                attribution=AuditAttribution(actor_id=operation.actor_id, correlation_id=operation.correlation_id),
            )
            current = self._operation_store.checkpoint(
                current.id,
                worker_id=worker_id,
                phase=OperationPhase.AUDIT,
                result_entity_id=document.id,
                audit_entry_hash=entry.entry_hash,
            )
        return cast(
            OperationRecord,
            self._operation_store.complete(
                current.id,
                worker_id=worker_id,
                result_entity_id=document.id,
            ),
        )


__all__ = ["EvidenceIngestionProjection"]
