# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import httpx

from solomon.api.app import create_app
from solomon.api.service import (
    CandidateClaimPromotionRequest,
    DependencyAssertionCreateRequest,
    DependencyAssertionDecisionRequest,
    DocumentSourceRequest,
    SolomonService,
    SourceDocumentIngestRequest,
)
from solomon.config import Settings
from solomon.consistency.models import ConsistencyFindingCode, ConsistencyScope, RepairPlan
from solomon.contracts import AuthoritySource, AuthoritySourceKind
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.store import GraphStore
from solomon.graph.suggestions import AssertionEvidenceKind, DependencyAssertionType, DependencySuggestion
from solomon.sources.models import DocumentSourceKind, SourceDocument


def test_consistency_inspection_plans_and_idempotently_repairs_missing_confirmed_edge(tmp_path: Path) -> None:
    service, assertion = _confirmed_assertion_service(tmp_path)
    edge_id = assertion.suggested_edge.id
    graph = cast(GraphStore, service.graph)
    with graph._conn:
        graph._conn.execute("DELETE FROM dependency_edges WHERE edge_id = ?", (edge_id,))

    report = service.consistency_check(matter_id="matter-a", client_id="client-a")
    assert ConsistencyFindingCode.CONFIRMED_ASSERTION_MISSING_EDGE in {finding.code for finding in report.findings}
    plan = service.consistency_repair_plan(matter_id="matter-a", client_id="client-a")
    assert [action.action for action in plan.actions] == ["reproject_confirmed_assertion_edge"]
    assert service.graph.get_dependencies(assertion.item_id) == []

    applied = service.apply_consistency_repair(plan)
    assert applied.applied is True
    assert [edge.id for edge in service.graph.get_dependencies(assertion.item_id)] == [edge_id]
    assert service.apply_consistency_repair(plan).idempotent is True


def test_consistency_repair_refuses_stale_and_cross_scope_plans(tmp_path: Path) -> None:
    service, assertion = _confirmed_assertion_service(tmp_path)
    graph = cast(GraphStore, service.graph)
    with graph._conn:
        graph._conn.execute("DELETE FROM dependency_edges WHERE edge_id = ?", (assertion.suggested_edge.id,))
    plan = service.consistency_repair_plan(matter_id="matter-a", client_id="client-a")
    current = service.get_dependency_assertion(assertion.id)
    service.graph.update_dependency_suggestion(current.model_copy(update={"state_version": current.state_version + 1}))

    stale = service.apply_consistency_repair(plan)
    assert stale.applied is False
    assert stale.refusal == "repair plan is stale because scoped consistency state changed"

    cross_scope = RepairPlan.create(
        scope=ConsistencyScope(tenant_id="other-tenant", matter_id="matter-a", client_id="client-a"),
        report_fingerprint=plan.report_fingerprint,
        actions=plan.actions,
    )
    denied = service.apply_consistency_repair(cross_scope)
    assert denied.applied is False
    assert denied.refusal == "repair plan tenant does not match the active service scope"


def test_consistency_reports_ambiguous_provenance_and_revision_gap_without_unsafe_edge_repair(tmp_path: Path) -> None:
    service, assertion = _confirmed_assertion_service(tmp_path)
    assert assertion.source_document_id is not None
    source = service.document_store.get_document(assertion.source_document_id)
    replacement = service.document_store.write_document(
        SourceDocument(
            source_id=source.source_id,
            external_id=source.external_id,
            filename=source.filename,
            mime_type=source.mime_type,
            content="updated source content",
        )
    )
    deferred = service.create_dependency_assertion(
        _request(assertion.item_id, assertion.source_document_id).model_copy(
            update={"idempotency_key": "deferred-assertion"}
        )
    )
    service.decide_dependency_assertion(
        deferred.id,
        DependencyAssertionDecisionRequest(by="reviewer-a", decision="deferred", reason="needs review"),
    )
    service.graph.add_dependency(
        deferred.suggested_edge.model_copy(update={"source_suggestion_id": deferred.id, "created_by": "test"})
    )

    report = service.consistency_check(matter_id="matter-a", client_id="client-a")
    codes = {finding.code for finding in report.findings}
    assert ConsistencyFindingCode.SOURCE_REVISION_OPERATION_MISSING in codes
    assert ConsistencyFindingCode.EDGE_INVALID_PROVENANCE in codes
    plan = service.consistency_repair_plan(matter_id="matter-a", client_id="client-a")
    assert all(action.assertion_id != deferred.id for action in plan.actions)
    assert any(action.replacement_document_id == replacement.id for action in plan.actions)
    assert service.graph.get_edge(deferred.suggested_edge.id).source_suggestion_id == deferred.id


def test_consistency_rest_contract_is_scoped_and_requires_explicit_apply(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal"))

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            scope = {"matter_id": "matter-a", "client_id": "client-a"}
            checked = await client.get("/consistency/check", params=scope)
            planned = await client.post("/consistency/repair/plan", params=scope)
            applied = await client.post("/consistency/repair/apply", json=planned.json())
            operations = await client.get("/consistency/operations", params=scope)
            return checked, planned, applied, operations

    checked, planned, applied, operations = asyncio.run(exercise())

    assert checked.status_code == planned.status_code == applied.status_code == operations.status_code == 200
    assert checked.json()["scope"] == {"tenant_id": None, "matter_id": "matter-a", "client_id": "client-a"}
    assert planned.json()["actions"] == []
    assert applied.json()["applied"] is True
    assert operations.json() == []


def _confirmed_assertion_service(tmp_path: Path) -> tuple[SolomonService, DependencySuggestion]:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
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
    assertion = service.create_dependency_assertion(_request(item.id, document.id))
    service.decide_dependency_assertion(
        assertion.id,
        DependencyAssertionDecisionRequest(by="reviewer-a", decision="confirmed"),
    )
    return service, assertion


def _request(item_id: str, document_id: str) -> DependencyAssertionCreateRequest:
    quote = "We rely on Regulation R section 12."
    return DependencyAssertionCreateRequest(
        item_id=item_id,
        source_document_id=document_id,
        source_document_version=1,
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
        idempotency_key="quote-assertion",
    )
