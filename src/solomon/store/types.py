# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from solomon.currency.models import CurrencyState, KnowledgeItem
from solomon.sources.models import CandidateClaim, CandidateClaimStatus, DocumentSource, SourceDocument
from solomon.workflow.models import AuthorityChangeEvent, ReviewTask, ReviewTaskState


@dataclass(frozen=True)
class KnowledgeEvent:
    seq: int
    event_type: str
    item_id: str
    occurred_at: datetime
    payload: dict[str, Any]


@runtime_checkable
class KnowledgeStoreProtocol(Protocol):
    def close(self) -> None: ...

    def write_item(self, item: KnowledgeItem) -> KnowledgeItem: ...

    def update_item(
        self,
        item: KnowledgeItem,
        *,
        event_type: str = "knowledge_item_updated",
        occurred_at: datetime | None = None,
    ) -> KnowledgeItem: ...

    def get_item(self, item_id: str) -> KnowledgeItem: ...

    def get_many(
        self,
        item_ids: Iterable[str] | None = None,
        *,
        include_states: set[CurrencyState] | None = None,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> list[KnowledgeItem]: ...

    def supersede(
        self,
        predecessor_id: str,
        successor: KnowledgeItem,
        *,
        superseded_at: datetime | None = None,
    ) -> tuple[KnowledgeItem, KnowledgeItem]: ...

    def as_of(self, timestamp: datetime) -> list[KnowledgeItem]: ...

    def list_events(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        event_types: set[str] | None = None,
    ) -> list[KnowledgeEvent]: ...


@runtime_checkable
class DocumentRepositoryProtocol(Protocol):
    def close(self) -> None: ...

    def upsert_source(self, source: DocumentSource) -> DocumentSource: ...

    def get_source(self, source_id: str) -> DocumentSource: ...

    def list_sources(self) -> list[DocumentSource]: ...

    def write_document(self, document: SourceDocument) -> SourceDocument: ...

    def get_document(self, document_id: str) -> SourceDocument: ...

    def list_documents(self, source_id: str) -> list[SourceDocument]: ...

    def document_versions(self, source_id: str, external_id: str) -> list[SourceDocument]: ...

    def tombstone_document(self, source_id: str, external_id: str) -> SourceDocument: ...

    def add_candidate(self, candidate: CandidateClaim) -> CandidateClaim: ...

    def get_candidate(self, candidate_id: str) -> CandidateClaim: ...

    def list_candidates(
        self,
        document_id: str,
        *,
        status: CandidateClaimStatus | None = None,
    ) -> list[CandidateClaim]: ...

    def update_candidate(self, candidate: CandidateClaim) -> CandidateClaim: ...


@runtime_checkable
class ReviewRepositoryProtocol(Protocol):
    def close(self) -> None: ...

    def record_authority_event(self, event: AuthorityChangeEvent) -> tuple[AuthorityChangeEvent, bool]: ...

    def get_authority_event(self, event_id: str) -> AuthorityChangeEvent: ...

    def create_review_task(self, task: ReviewTask) -> ReviewTask: ...

    def get_review_task(self, task_id: str) -> ReviewTask: ...

    def list_review_tasks(
        self,
        *,
        reviewer_id: str | None = None,
        state: ReviewTaskState | None = None,
    ) -> list[ReviewTask]: ...

    def assign(self, task_id: str, *, reviewer_id: str, assigned_by: str) -> ReviewTask: ...

    def start(self, task_id: str, *, reviewer_id: str) -> ReviewTask: ...

    def resolve(self, task_id: str, *, reviewer_id: str) -> ReviewTask: ...
