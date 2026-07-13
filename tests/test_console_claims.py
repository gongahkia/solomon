# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from solomon.api.service import SolomonService
from solomon.api.service_models import DocumentSourceRequest, SourceDocumentIngestRequest
from solomon.console.app import create_console_app
from solomon.sources.models import CandidateClaimStatus, DocumentSourceKind


def test_console_claims_show_evidence_and_record_decisions(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    source = service.register_document_source(
        DocumentSourceRequest(name="shared", kind=DocumentSourceKind.FILESYSTEM, root_ref="/knowledge")
    )
    document, candidates = service.ingest_source_document(
        source.id,
        SourceDocumentIngestRequest(
            external_id="memo-1",
            filename="memo.txt",
            content="First reusable position from evidence.\n\nSecond reusable position requires later review.",
        ),
    )
    app = create_console_app(service=service)

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            page = await client.get("/console/claims")
            promoted = await client.post(f"/console/claims/{candidates[0].id}/promote", data={"by": "curator-a"})
            deferred = await client.post(
                f"/console/claims/{candidates[1].id}/defer",
                data={"by": "curator-a", "reason": "needs matter context"},
            )
            return page, promoted, deferred

    page, promoted, deferred = asyncio.run(exercise())

    assert page.status_code == 200
    assert document.filename in page.text
    assert candidates[0].content in page.text
    assert promoted.status_code == 200
    assert deferred.status_code == 200
    assert service.document_store.get_candidate(candidates[0].id).status is CandidateClaimStatus.PROMOTED
    assert service.document_store.get_candidate(candidates[1].id).status is CandidateClaimStatus.DEFERRED
    events = [entry.event_type for entry in service.audit.list_entries()]
    assert "candidate_claim_promoted" in events
    assert "candidate_claim_deferred" in events
