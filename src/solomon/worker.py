# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from solomon.api.schemas import SolomonModel
from solomon.api.service import SolomonService
from solomon.errors import SolomonError
from solomon.sources.models import DocumentSourceKind


class DocumentSourceWorkerBatch(SolomonModel):
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0


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


__all__ = ["DocumentSourceWorkerBatch", "sync_enabled_filesystem_sources"]
