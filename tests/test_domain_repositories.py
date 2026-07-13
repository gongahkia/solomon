# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone

from solomon.sources.models import CandidateClaim, DocumentSource, DocumentSourceKind, SourceDocument
from solomon.sources.store import SQLiteDocumentStore
from solomon.store.types import DocumentRepositoryProtocol, ReviewRepositoryProtocol
from solomon.workflow.models import AuthorityChangeEvent, ReviewTask, ReviewTaskPriority, ReviewTaskState
from solomon.workflow.store import SQLiteWorkflowStore


def test_document_repository_contract_persists_source_document_versions_and_claims(tmp_path):
    repository: DocumentRepositoryProtocol = SQLiteDocumentStore(tmp_path / "sources.sqlite3")
    source = repository.upsert_source(
        DocumentSource(id="source-1", name="filesystem", kind=DocumentSourceKind.FILESYSTEM, root_ref="/knowledge")
    )
    first = repository.write_document(
        SourceDocument(
            id="document-1",
            source_id=source.id,
            external_id="memo-1",
            filename="memo.txt",
            mime_type="text/plain",
            content="Original reusable proposition.",
        )
    )
    second = repository.write_document(
        SourceDocument(
            id="document-2",
            source_id=source.id,
            external_id="memo-1",
            filename="memo.txt",
            mime_type="text/plain",
            content="Updated reusable proposition.",
        )
    )
    claim = repository.add_candidate(
        CandidateClaim(id="claim-1", document_id=second.id, content=second.content, start_offset=0, end_offset=29)
    )

    assert isinstance(repository, DocumentRepositoryProtocol)
    assert repository.document_versions(source.id, "memo-1") == [first, second]
    assert repository.get_candidate(claim.id) == claim
    repository.close()


def test_review_repository_contract_persists_idempotent_events_and_state_transitions(tmp_path):
    repository: ReviewRepositoryProtocol = SQLiteWorkflowStore(tmp_path / "workflow.sqlite3")
    event = AuthorityChangeEvent(
        id="event-1",
        source_id="authority-feed",
        idempotency_key="official:v2",
        authority_id="regulation-r-12",
        new_version="v2",
        changed_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
    )
    recorded, created = repository.record_authority_event(event)
    duplicate, duplicate_created = repository.record_authority_event(event)
    task = repository.create_review_task(
        ReviewTask(
            id="task-1",
            event_id=recorded.id,
            item_id="item-1",
            priority=ReviewTaskPriority.HIGH,
            reason="authority version changed",
        )
    )
    assigned = repository.assign(task.id, reviewer_id="lawyer-a", assigned_by="curator-a")
    in_review = repository.start(task.id, reviewer_id="lawyer-a")
    resolved = repository.resolve(task.id, reviewer_id="lawyer-a")

    assert isinstance(repository, ReviewRepositoryProtocol)
    assert created is True
    assert duplicate == recorded
    assert duplicate_created is False
    assert assigned.state is ReviewTaskState.ASSIGNED
    assert in_review.state is ReviewTaskState.IN_REVIEW
    assert resolved.state is ReviewTaskState.RESOLVED
    repository.close()
