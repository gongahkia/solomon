# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from solomon.api.schemas import SolomonModel
from solomon.api.service import SolomonService
from solomon.errors import SolomonError
from solomon.operations.models import OperationStatus
from solomon.sources.models import DocumentSourceKind


class DocumentSourceWorkerBatch(SolomonModel):
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0


class OperationWorkerBatch(SolomonModel):
    attempted: int = 0
    completed: int = 0
    retrying: int = 0
    terminal: int = 0
    failed: int = 0


def sync_enabled_filesystem_sources(service: SolomonService, *, limit: int = 100) -> DocumentSourceWorkerBatch:
    if limit < 1:
        raise ValueError("limit must be at least one")
    attempted = 0
    succeeded = 0
    failed = 0
    skipped = 0
    for source in service.document_store.list_sources():
        if not source.enabled or source.kind is not DocumentSourceKind.FILESYSTEM:
            skipped += 1
            continue
        if attempted >= limit:
            skipped += 1
            continue
        attempted += 1
        try:
            service.sync_document_source(source.id)
        except SolomonError:
            failed += 1
        else:
            succeeded += 1
    return DocumentSourceWorkerBatch(attempted=attempted, succeeded=succeeded, failed=failed, skipped=skipped)


def run_pending_operations(
    service: SolomonService,
    *,
    worker_id: str,
    limit: int = 100,
) -> OperationWorkerBatch:
    """Drain currently eligible durable operations; delayed retries wait for a later worker cycle."""

    if not worker_id or limit < 1:
        raise ValueError("worker ID and positive limit are required")
    attempted = completed = retrying = terminal = failed = 0
    try:
        service._authority.reconcile_evidence_ingestions()
    except Exception:
        failed += 1
    try:
        service._authority.reconcile_source_revisions()
    except Exception:
        failed += 1
    for _ in range(limit):
        try:
            operation = service._authority.run_operation_once(worker_id=worker_id)
        except Exception:
            failed += 1
            break
        if operation is None:
            break
        attempted += 1
        if operation.status is OperationStatus.COMPLETED:
            completed += 1
        elif operation.status is OperationStatus.RETRYING:
            retrying += 1
        elif operation.status in {OperationStatus.TERMINAL_FAILED, OperationStatus.OPERATOR_REQUIRED}:
            terminal += 1
    return OperationWorkerBatch(
        attempted=attempted,
        completed=completed,
        retrying=retrying,
        terminal=terminal,
        failed=failed,
    )


__all__ = [
    "DocumentSourceWorkerBatch",
    "OperationWorkerBatch",
    "run_pending_operations",
    "sync_enabled_filesystem_sources",
]
