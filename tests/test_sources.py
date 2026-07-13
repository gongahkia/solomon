# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest

from solomon.api.service import SolomonService
from solomon.api.service_models import (
    CandidateClaimPromotionRequest,
    CandidateClaimRejectionRequest,
    DocumentSourceRequest,
    RecallRequest,
    SourceDocumentIngestRequest,
)
from solomon.errors import BadRequestError
from solomon.sources.extract import MAX_DOCUMENT_BYTES, extract_document_bytes
from solomon.sources.models import (
    CandidateClaim,
    CandidateClaimStatus,
    DocumentSource,
    DocumentSourceKind,
    SourceDocument,
)
from solomon.sources.store import (
    CandidateClaimNotFoundError,
    SourceDocumentNotFoundError,
    SourceNotFoundError,
    SQLiteDocumentStore,
)


def test_document_store_versions_documents_and_candidates(tmp_path):
    store = SQLiteDocumentStore(tmp_path / "sources.sqlite3")
    source = store.upsert_source(
        DocumentSource(name="shared drive", kind=DocumentSourceKind.FILESYSTEM, root_ref="/knowledge")
    )
    first = store.write_document(
        SourceDocument(
            source_id=source.id,
            external_id="memo-1",
            filename="memo.txt",
            mime_type="text/plain",
            content="First version of the position.",
        )
    )
    unchanged = store.write_document(
        SourceDocument(
            source_id=source.id,
            external_id="memo-1",
            filename="memo.txt",
            mime_type="text/plain",
            content="First version of the position.",
        )
    )
    second = store.write_document(
        SourceDocument(
            source_id=source.id,
            external_id="memo-1",
            filename="memo.txt",
            mime_type="text/plain",
            content="Second version of the position.",
        )
    )

    assert unchanged.id == first.id
    assert second.version == 2
    assert second.previous_version_id == first.id
    candidate = store.add_candidate(
        CandidateClaim(document_id=second.id, content="Second version of the position.", start_offset=0, end_offset=31)
    )
    assert store.list_candidates(second.id) == [candidate]

    updated = store.update_candidate(candidate.model_copy(update={"status": CandidateClaimStatus.REJECTED}))
    assert updated.status is CandidateClaimStatus.REJECTED


def test_extract_docx_and_reject_image_only_pdf():
    payload = BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>Current clause text.</w:t></w:r></w:p></w:body>
            </w:document>
            """,
        )
    extracted = extract_document_bytes(payload.getvalue(), filename="clause.docx")
    assert extracted.text == "Current clause text."
    assert extracted.state.value == "ready"

    pdf = extract_document_bytes(b"not-a-pdf", filename="scan.pdf")
    assert pdf.state.value == "rejected"


def test_extraction_covers_supported_and_rejected_inputs():
    html = extract_document_bytes(b"<h1>Title</h1><p>Current internal position.</p>", filename="memo.html")
    assert html.text == "Title\nCurrent internal position."
    assert html.state.value == "ready"
    assert extract_document_bytes(b"", filename="empty.txt").reason == "document contains no extractable text"
    assert extract_document_bytes(b"not a zip", filename="bad.docx").state.value == "rejected"
    unsupported = extract_document_bytes(b"data", filename="opaque.bin", mime_type="application/octet-stream")
    assert unsupported.state.value == "rejected"
    oversized = extract_document_bytes(b"x" * (MAX_DOCUMENT_BYTES + 1), filename="large.txt")
    assert oversized.reason == "document exceeds extraction byte limit"


def test_source_document_claim_requires_human_promotion(tmp_path):
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    source = service.register_document_source(
        DocumentSourceRequest(name="internal", kind=DocumentSourceKind.FILESYSTEM, root_ref="/knowledge")
    )
    document, candidates = service.ingest_source_document(
        source.id,
        SourceDocumentIngestRequest(
            external_id="memo-1",
            filename="memo.txt",
            content=(
                "Structure X is compliant under Regulation R section 12.\n\n"
                "Review remains necessary after a source change."
            ),
        ),
    )

    assert document.version == 1
    assert len(candidates) == 2
    assert service.recall(RecallRequest(query="structure X")) == []

    item = service.promote_candidate_claim(
        candidates[0].id,
        CandidateClaimPromotionRequest(by="curator-a", author="Curator A"),
    )
    recalled = service.recall(RecallRequest(query="structure X"))
    promoted = service.document_store.get_candidate(candidates[0].id)

    assert recalled[0]["item"]["id"] == item.id
    assert promoted.status is CandidateClaimStatus.PROMOTED
    assert promoted.promotion_item_id == item.id
    with pytest.raises(BadRequestError, match="only pending"):
        service.promote_candidate_claim(candidates[0].id, CandidateClaimPromotionRequest(by="curator-a"))
    rejected = service.reject_candidate_claim(
        candidates[1].id,
        CandidateClaimRejectionRequest(by="curator-a", reason="not a reusable claim"),
    )
    assert rejected.status is CandidateClaimStatus.REJECTED
    with pytest.raises(ValueError, match="exactly one"):
        SourceDocumentIngestRequest(external_id="memo-2", filename="memo.txt")


def test_document_store_lists_versions_tombstones_and_missing_records(tmp_path):
    store = SQLiteDocumentStore(tmp_path / "sources.sqlite3")
    source = store.upsert_source(DocumentSource(name="source", kind=DocumentSourceKind.API, root_ref="api://source"))
    document = store.write_document(
        SourceDocument(
            source_id=source.id,
            external_id="a",
            filename="a.txt",
            mime_type="text/plain",
            content="A reusable internal proposition.",
        )
    )
    tombstone = store.tombstone_document(source.id, "a")

    assert store.list_sources() == [source]
    assert store.list_documents(source.id) == [document, tombstone]
    assert store.document_versions(source.id, "a") == [document, tombstone]
    assert tombstone.extraction_state.value == "deleted"
    with pytest.raises(SourceNotFoundError):
        store.get_source("missing")
    with pytest.raises(SourceDocumentNotFoundError):
        store.get_document("missing")
    with pytest.raises(SourceDocumentNotFoundError):
        store.tombstone_document(source.id, "missing")
    with pytest.raises(CandidateClaimNotFoundError):
        store.get_candidate("missing")


def test_document_sources_validate_filesystem_and_microsoft_graph_root_references():
    with pytest.raises(ValueError, match="absolute path"):
        DocumentSource(name="relative", kind=DocumentSourceKind.FILESYSTEM, root_ref="knowledge")
    with pytest.raises(ValueError, match="Microsoft Graph"):
        DocumentSource(
            name="wrong graph", kind=DocumentSourceKind.MICROSOFT_GRAPH, root_ref="https://example.test/v1.0/sites"
        )
    graph = DocumentSource(
        name="microsoft 365",
        kind=DocumentSourceKind.MICROSOFT_GRAPH,
        root_ref="https://graph.microsoft.com/v1.0/sites/site-1",
    )
    assert graph.root_ref.endswith("site-1")
