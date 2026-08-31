# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from solomon.api.service import (
    CandidateClaimPromotionRequest,
    DependencyAssertionCreateRequest,
    DependencyAssertionDecisionRequest,
    DocumentSourceRequest,
    SolomonService,
    SourceDocumentIngestRequest,
)
from solomon.contracts import AuthoritySource, AuthoritySourceKind
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.errors import BadRequestError
from solomon.graph.suggestions import AssertionEvidenceKind, DependencyAssertionType, SuggestionDecision
from solomon.operations.failure_injection import OperationFailureInjector
from solomon.operations.models import OperationStatus, OperationType
from solomon.sources.models import DocumentSourceKind
from solomon.store.postgres import PostgresDependencyError

pytestmark = pytest.mark.integration


def test_live_mixed_sqlite_documents_and_postgres_projections_resume_once(tmp_path: Path) -> None:
    dsn = os.environ.get("SOLOMON_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set SOLOMON_TEST_POSTGRES_DSN to run live mixed-store integration coverage")

    psycopg = pytest.importorskip("psycopg")
    schema = f"test_mixed_{uuid.uuid4().hex}"
    data_dir = tmp_path / "data"
    journal_dir = tmp_path / "journal"
    first = restarted = None
    try:
        try:
            first = SolomonService(
                data_dir=data_dir,
                journal_dir=journal_dir,
                database_url=dsn,
                postgres_schema=schema,
                tenant_id="tenant-a",
            )
        except PostgresDependencyError as exc:
            pytest.skip(str(exc))
        source = first.register_document_source(
            DocumentSourceRequest(
                source_id="matter-documents",
                name="matter documents",
                kind=DocumentSourceKind.FILESYSTEM,
                root_ref="/matter-documents",
            )
        )
        document, candidates = first.ingest_source_document(
            source.id,
            SourceDocumentIngestRequest(
                external_id="memo-1",
                filename="memo.txt",
                mime_type="text/plain",
                content="We rely on Regulation R section 12. The conclusion applies to the operating rule.",
            ),
        )
        item = first.promote_candidate_claim(
            candidates[0].id,
            CandidateClaimPromotionRequest(
                by="curator-a",
                kind=KnowledgeKind.POSITION,
                source_kind=SourceKind.MATTER_DOC,
                matter_id="matter-a",
                client_id="client-a",
            ),
        )
        first.register_authority_source(
            AuthoritySource(
                id="official-gazette",
                name="Official Gazette",
                kind=AuthoritySourceKind.FEED,
                root_ref="https://gazette.example.test/feed",
            )
        )
        quote = "We rely on Regulation R section 12."
        assertion = first.create_dependency_assertion(
            DependencyAssertionCreateRequest(
                item_id=item.id,
                source_document_id=document.id,
                source_document_version=document.version,
                target_kind="external_authority",
                authority_source_id="official-gazette",
                authority_identifier="SG-REG-12",
                assertion_type=DependencyAssertionType.NORMATIVE_POLICY,
                evidence_kind=AssertionEvidenceKind.QUOTE,
                quote=quote,
                quote_start=0,
                quote_end=len(quote),
                rationale="the internal position adopts the registered authority",
                created_by="curator-a",
                idempotency_key="mixed-store-assertion",
            )
        )
        first._authority.set_operation_failure_injector(OperationFailureInjector(["after_graph_edge_before_ack"]))
        with pytest.raises(BadRequestError, match="durably queued"):
            first.decide_dependency_assertion(
                assertion.id,
                DependencyAssertionDecisionRequest(by="reviewer-a", decision="confirmed"),
            )
        operation = next(
            current
            for current in first.operation_store.list()
            if current.operation_type is OperationType.ASSERTION_CONFIRM
        )
        assert operation.status is OperationStatus.RETRYING
        assert first.graph.get_dependencies(item.id)[0].source_suggestion_id == assertion.id
        assert first.document_store.get_document(document.id).content_sha256 == assertion.source_document_sha256

        _close_service(first)
        first = None
        restarted = SolomonService(
            data_dir=data_dir,
            journal_dir=journal_dir,
            database_url=dsn,
            postgres_schema=schema,
            tenant_id="tenant-a",
        )
        assert operation.next_eligible_retry_at is not None
        recovered = restarted._authority.run_operation_once(
            worker_id="mixed-store-restarted",
            now=operation.next_eligible_retry_at,
        )

        assert recovered is not None
        assert recovered.status is OperationStatus.COMPLETED
        assert restarted.get_dependency_assertion(assertion.id).decision is SuggestionDecision.CONFIRMED
        assert [edge.source_suggestion_id for edge in restarted.graph.get_dependencies(item.id)] == [assertion.id]
        assert restarted.document_store.get_document(document.id).content_sha256 == assertion.source_document_sha256
        operation_events = [
            entry.event_type
            for entry in restarted.audit.list_entries()
            if str(entry.payload.get("operation_id", "")).startswith(f"{operation.id}:")
        ]
        assert operation_events == ["dependency_assertion_confirmed", "dependency_assertion_edge_linked"]
    finally:
        if first is not None:
            _close_service(first)
        if restarted is not None:
            _close_service(restarted)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _close_service(service: SolomonService) -> None:
    service.operation_store.close()
    service.store.close()
    service.graph.close()
    service.index.close()
