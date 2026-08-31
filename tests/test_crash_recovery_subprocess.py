# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from solomon.api.service import (
    CandidateClaimPromotionRequest,
    DependencyAssertionCreateRequest,
    DocumentSourceRequest,
    SolomonService,
    SourceDocumentIngestRequest,
)
from solomon.contracts import AuthoritySource, AuthoritySourceKind
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.suggestions import (
    AssertionEvidenceKind,
    DependencyAssertionType,
    DependencySuggestion,
    SuggestionDecision,
)
from solomon.operations.models import OperationStatus
from solomon.sources.models import DocumentSourceKind
from solomon.store.postgres import PostgresDependencyError

pytestmark = pytest.mark.integration

_CHILD = """
import os
from pathlib import Path

from solomon.api.service import DependencyAssertionDecisionRequest, SolomonService
from solomon.operations.failure_injection import SubprocessKillOperationFailureInjector

service = SolomonService(
    data_dir=Path(os.environ["SOLOMON_CRASH_DATA_DIR"]),
    journal_dir=Path(os.environ["SOLOMON_CRASH_JOURNAL_DIR"]),
    database_url=os.environ["SOLOMON_CRASH_DATABASE_URL"],
    postgres_schema=os.environ["SOLOMON_CRASH_SCHEMA"],
    tenant_id="tenant-a",
)
service._authority.set_operation_failure_injector(
    SubprocessKillOperationFailureInjector(["after_graph_edge_before_ack"])
)
service.decide_dependency_assertion(
    os.environ["SOLOMON_CRASH_ASSERTION_ID"],
    DependencyAssertionDecisionRequest(by="reviewer-a", decision="confirmed"),
)
"""


def test_sigkill_after_edge_projection_recovers_once_with_real_mixed_stores(tmp_path: Path) -> None:
    dsn = os.environ.get("SOLOMON_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set SOLOMON_TEST_POSTGRES_DSN to run subprocess crash recovery coverage")

    psycopg = pytest.importorskip("psycopg")
    schema = f"test_crash_{uuid.uuid4().hex}"
    data_dir = tmp_path / "data"
    journal_dir = tmp_path / "journal"
    initial = restarted = None
    try:
        try:
            initial, assertion, item_id, document_id = _prepare_service(
                dsn=dsn,
                schema=schema,
                data_dir=data_dir,
                journal_dir=journal_dir,
            )
        except PostgresDependencyError as exc:
            pytest.skip(str(exc))
        _close(initial)
        initial = None
        environment = {
            **os.environ,
            "SOLOMON_CRASH_DATA_DIR": str(data_dir),
            "SOLOMON_CRASH_JOURNAL_DIR": str(journal_dir),
            "SOLOMON_CRASH_DATABASE_URL": dsn,
            "SOLOMON_CRASH_SCHEMA": schema,
            "SOLOMON_CRASH_ASSERTION_ID": assertion.id,
        }
        child = subprocess.run(  # noqa: S603 -- fixed interpreter and in-module test script only
            [sys.executable, "-c", _CHILD],
            env=environment,
            check=False,
            timeout=15,
            capture_output=True,
            text=True,
        )
        assert child.returncode == -9
        assert child.stdout == ""

        restarted = SolomonService(
            data_dir=data_dir,
            journal_dir=journal_dir,
            database_url=dsn,
            postgres_schema=schema,
            tenant_id="tenant-a",
        )
        operation = restarted.operation_store.list()[0]
        assert operation.status is OperationStatus.CLAIMED
        assert restarted.graph.get_dependencies(item_id)[0].source_suggestion_id == assertion.id
        assert operation.lease_expires_at is not None
        recovered = restarted._authority.run_operation_once(
            worker_id="subprocess-restarted",
            now=operation.lease_expires_at,
        )

        assert recovered is not None
        assert recovered.status is OperationStatus.COMPLETED
        assert restarted.get_dependency_assertion(assertion.id).decision is SuggestionDecision.CONFIRMED
        assert [edge.source_suggestion_id for edge in restarted.graph.get_dependencies(item_id)] == [assertion.id]
        assert restarted.document_store.get_document(document_id).content_sha256 == assertion.source_document_sha256
        assert [entry.event_type for entry in restarted.audit.list_entries() if entry.payload.get("operation_id")] == [
            "dependency_assertion_confirmed",
            "dependency_assertion_edge_linked",
        ]
    finally:
        if initial is not None:
            _close(initial)
        if restarted is not None:
            _close(restarted)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _prepare_service(
    *,
    dsn: str,
    schema: str,
    data_dir: Path,
    journal_dir: Path,
) -> tuple[SolomonService, DependencySuggestion, str, str]:
    service = SolomonService(
        data_dir=data_dir,
        journal_dir=journal_dir,
        database_url=dsn,
        postgres_schema=schema,
        tenant_id="tenant-a",
    )
    source = service.register_document_source(
        DocumentSourceRequest(
            source_id="matter-documents",
            name="matter documents",
            kind=DocumentSourceKind.FILESYSTEM,
            root_ref="/matter-documents",
        )
    )
    document, candidates = service.ingest_source_document(
        source.id,
        SourceDocumentIngestRequest(
            external_id="memo-1",
            filename="memo.txt",
            mime_type="text/plain",
            content="We rely on Regulation R section 12. The conclusion applies to the operating rule.",
        ),
    )
    item = service.promote_candidate_claim(
        candidates[0].id,
        CandidateClaimPromotionRequest(
            by="curator-a",
            kind=KnowledgeKind.POSITION,
            source_kind=SourceKind.MATTER_DOC,
            matter_id="matter-a",
            client_id="client-a",
        ),
    )
    service.register_authority_source(
        AuthoritySource(
            id="official-gazette",
            name="Official Gazette",
            kind=AuthoritySourceKind.FEED,
            root_ref="https://gazette.example.test/feed",
        )
    )
    quote = "We rely on Regulation R section 12."
    assertion = service.create_dependency_assertion(
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
            idempotency_key="subprocess-crash-assertion",
        )
    )
    return service, assertion, item.id, document.id


def _close(service: SolomonService) -> None:
    service.operation_store.close()
    service.store.close()
    service.graph.close()
    service.index.close()
