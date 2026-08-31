# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from solomon.api.app import create_app
from solomon.api.service import (
    CandidateClaimPromotionRequest,
    DependencyAssertionCreateRequest,
    DependencyAssertionDecisionRequest,
    DependencyAssertionWithdrawRequest,
    DocumentSourceRequest,
    SolomonService,
    SourceDocumentIngestRequest,
)
from solomon.client import AsyncSolomonClient
from solomon.config import Settings
from solomon.contracts import AuthoritySource, AuthoritySourceKind
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.errors import BadRequestError, ConflictError, NotFoundError, PolicyRefusalError
from solomon.graph.models import DependencyEdge
from solomon.graph.suggestions import (
    AssertionEvidenceKind,
    DependencyAssertionType,
    DependencySuggestion,
    SuggestionDecision,
)
from solomon.mcp.tools import SolomonMCPRuntime
from solomon.operations.failure_injection import InjectedOperationFailure, OperationFailureInjector
from solomon.operations.models import OperationStatus, OperationType
from solomon.sources.models import DocumentSourceKind, SourceDocument
from solomon.worker import run_pending_operations


def test_governed_assertion_requires_reconstructible_registered_evidence_and_confirmed_edge(tmp_path: Path) -> None:
    service, document_id, item_id = _source_backed_service(tmp_path)
    service.register_authority_source(_authority_source())
    request = _quote_request(item_id=item_id, document_id=document_id)

    assertion = service.create_dependency_assertion(request)
    replay = service.create_dependency_assertion(request)

    assert assertion.id == replay.id
    assert assertion.decision is SuggestionDecision.PENDING
    assert service.graph.get_dependencies(item_id) == []
    assert assertion.source_document_sha256
    assert assertion.suggested_edge.target_id.startswith("authority:official-gazette:")

    with pytest.raises(PolicyRefusalError, match="creator cannot"):
        service.decide_dependency_assertion(
            assertion.id,
            DependencyAssertionDecisionRequest(by="curator-a", decision="confirmed"),
        )

    edge = service.decide_dependency_assertion(
        assertion.id,
        DependencyAssertionDecisionRequest(by="reviewer-a", decision="confirmed", reason="source reviewed"),
    )

    assert isinstance(edge, DependencyEdge)
    assert edge.source_suggestion_id == assertion.id
    assert len(service.graph.get_dependencies(item_id)) == 1
    history = service.dependency_assertion_history(assertion.id, matter_id="matter-a", client_id="client-a")
    assert history["edge"]["id"] == edge.id
    assert {entry["event_type"] for entry in history["audit_entries"]} >= {
        "dependency_assertion_created",
        "dependency_assertion_confirmed",
        "dependency_assertion_edge_linked",
    }


def test_governed_assertion_rejects_invalid_evidence_targets_and_cross_scope_before_persistence(tmp_path: Path) -> None:
    service, document_id, item_id = _source_backed_service(tmp_path)
    service.register_authority_source(_authority_source())
    bad_offsets = _quote_request(item_id=item_id, document_id=document_id).model_copy(
        update={"quote_start": 1, "quote_end": 4, "quote": "bad", "idempotency_key": "bad-offset"}
    )
    with pytest.raises(BadRequestError, match="quote offsets"):
        service.create_dependency_assertion(bad_offsets)

    missing_target = _quote_request(item_id=item_id, document_id=document_id).model_copy(
        update={"target_item_id": "missing", "target_kind": "knowledge_item", "idempotency_key": "missing-target"}
    )
    with pytest.raises(NotFoundError):
        service.create_dependency_assertion(missing_target)

    other_document_id, other_item_id = _source_backed_item(service, matter_id="matter-b", client_id="client-b")
    cross_scope = _quote_request(item_id=item_id, document_id=document_id).model_copy(
        update={
            "target_kind": "knowledge_item",
            "target_item_id": other_item_id,
            "authority_source_id": None,
            "authority_identifier": None,
            "idempotency_key": "cross-scope",
        }
    )
    with pytest.raises(PolicyRefusalError, match="cross matter"):
        service.create_dependency_assertion(cross_scope)
    assert service.dependency_assertions(matter_id="matter-b", client_id="client-b") == []
    assert other_document_id


def test_governed_commentary_defer_withdraw_scope_and_revision_reverification(tmp_path: Path) -> None:
    service, document_id, item_id = _source_backed_service(tmp_path)
    service.register_authority_source(_authority_source())
    assertion = service.create_dependency_assertion(
        DependencyAssertionCreateRequest(
            item_id=item_id,
            source_document_id=document_id,
            source_document_version=1,
            target_kind="external_authority",
            authority_source_id="official-gazette",
            authority_identifier="SG-REG-12",
            assertion_type=DependencyAssertionType.PROCEDURAL,
            evidence_kind=AssertionEvidenceKind.COMMENTARY,
            commentary="The reviewer links the implementation procedure to this registered authority.",
            rationale="operational control dependency",
            created_by="curator-a",
            idempotency_key="commentary-assertion",
        )
    )
    deferred = service.decide_dependency_assertion(
        assertion.id,
        DependencyAssertionDecisionRequest(by="reviewer-a", decision="deferred", reason="need second review"),
    )
    assert not isinstance(deferred, DependencyEdge)
    assert deferred.decision is SuggestionDecision.DEFERRED
    withdrawn = service.withdraw_dependency_assertion(
        assertion.id,
        DependencyAssertionWithdrawRequest(by="curator-a", reason="superseded evidence"),
    )
    assert withdrawn.decision is SuggestionDecision.WITHDRAWN
    assert service.graph.get_dependencies(item_id) == []
    with pytest.raises(NotFoundError):
        service.get_dependency_assertion(assertion.id, matter_id="matter-b", client_id="client-b")

    quote_assertion = service.create_dependency_assertion(_quote_request(item_id=item_id, document_id=document_id))
    service.ingest_source_document(
        "matter-documents",
        SourceDocumentIngestRequest(
            external_id="memo-1",
            filename="memo.txt",
            mime_type="text/plain",
            content="We rely on Regulation R section 12 to implement the revised operating rule.",
        ),
    )
    reverified = service.get_dependency_assertion(quote_assertion.id, matter_id="matter-a", client_id="client-a")
    assert reverified.needs_reverification is True
    assert reverified.reverification_audit_id is not None
    assert reverified.evidence_raw == "We rely on Regulation R section 12."


def test_governed_assertion_concurrent_confirmation_has_one_edge(tmp_path: Path) -> None:
    service, document_id, item_id = _source_backed_service(tmp_path)
    service.register_authority_source(_authority_source())
    assertion = service.create_dependency_assertion(_quote_request(item_id=item_id, document_id=document_id))

    def confirm() -> DependencyEdge:
        outcome = service.decide_dependency_assertion(
            assertion.id,
            DependencyAssertionDecisionRequest(by="reviewer-a", decision="confirmed"),
        )
        assert isinstance(outcome, DependencyEdge)
        return outcome

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: confirm(), range(2)))

    assert {outcome.id for outcome in outcomes} == {assertion.suggested_edge.id}
    assert [edge.source_suggestion_id for edge in service.graph.get_dependencies(item_id)] == [assertion.id]


def test_governed_confirmation_crash_after_edge_retries_without_duplicate_edge_or_audit(tmp_path: Path) -> None:
    service, document_id, item_id = _source_backed_service(tmp_path)
    service.register_authority_source(_authority_source())
    assertion = service.create_dependency_assertion(_quote_request(item_id=item_id, document_id=document_id))
    service._authority.set_operation_failure_injector(OperationFailureInjector(["after_graph_edge_before_ack"]))

    with pytest.raises(BadRequestError, match="durably queued"):
        service.decide_dependency_assertion(
            assertion.id,
            DependencyAssertionDecisionRequest(by="reviewer-a", decision="confirmed"),
    )
    operation = next(
        current
        for current in service.operation_store.list()
        if current.operation_type is OperationType.ASSERTION_CONFIRM
    )
    assert operation.status is OperationStatus.RETRYING
    assert service.graph.get_dependencies(item_id)[0].source_suggestion_id == assertion.id
    assert service.get_dependency_assertion(assertion.id).decision is SuggestionDecision.PENDING

    assert operation.next_eligible_retry_at is not None
    recovered = service._authority.run_operation_once(
        worker_id="worker-restarted",
        now=operation.next_eligible_retry_at,
    )
    assert recovered is not None
    assert recovered.status is OperationStatus.COMPLETED
    assert [edge.source_suggestion_id for edge in service.graph.get_dependencies(item_id)] == [assertion.id]
    audit_events = [
        entry
        for entry in service.audit.list_entries()
        if str(entry.payload.get("operation_id", "")).startswith(f"{operation.id}:")
    ]
    assert [entry.event_type for entry in audit_events] == [
        "dependency_assertion_confirmed",
        "dependency_assertion_edge_linked",
    ]


def test_governed_confirmation_failure_before_authoritative_operation_leaves_no_projection(tmp_path: Path) -> None:
    service, document_id, item_id = _source_backed_service(tmp_path)
    service.register_authority_source(_authority_source())
    assertion = service.create_dependency_assertion(_quote_request(item_id=item_id, document_id=document_id))
    service._authority.set_operation_failure_injector(OperationFailureInjector(["before_authoritative_write"]))

    with pytest.raises(InjectedOperationFailure, match="before_authoritative_write"):
        service.decide_dependency_assertion(
            assertion.id,
            DependencyAssertionDecisionRequest(by="reviewer-a", decision="confirmed"),
        )

    assert not any(
        current.operation_type is OperationType.ASSERTION_CONFIRM for current in service.operation_store.list()
    )
    assert service.graph.get_dependencies(item_id) == []
    assert service.get_dependency_assertion(assertion.id).decision is SuggestionDecision.PENDING


@pytest.mark.parametrize(
    "point",
    ["during_graph_edge_projection", "during_currency_propagation", "after_currency_before_audit"],
)
def test_governed_confirmation_resumes_each_projection_checkpoint_once(tmp_path: Path, point: str) -> None:
    service, document_id, item_id = _source_backed_service(tmp_path)
    service.register_authority_source(_authority_source())
    assertion = service.create_dependency_assertion(_quote_request(item_id=item_id, document_id=document_id))
    service._authority.set_operation_failure_injector(OperationFailureInjector([point]))

    with pytest.raises(BadRequestError, match="durably queued"):
        service.decide_dependency_assertion(
            assertion.id,
            DependencyAssertionDecisionRequest(by="reviewer-a", decision="confirmed"),
    )
    operation = next(
        current
        for current in service.operation_store.list()
        if current.operation_type is OperationType.ASSERTION_CONFIRM
    )
    assert operation.status is OperationStatus.RETRYING
    assert operation.next_eligible_retry_at is not None

    service._authority.set_operation_failure_injector(OperationFailureInjector())
    recovered = service._authority.run_operation_once(
        worker_id="checkpoint-restarted",
        now=operation.next_eligible_retry_at,
    )

    assert recovered is not None
    assert recovered.status is OperationStatus.COMPLETED
    assert [edge.source_suggestion_id for edge in service.graph.get_dependencies(item_id)] == [assertion.id]
    assert service.get_dependency_assertion(assertion.id).decision is SuggestionDecision.CONFIRMED
    assert [
        entry.event_type
        for entry in service.audit.list_entries()
        if str(entry.payload.get("operation_id", "")).startswith(f"{operation.id}:")
    ] == [
        "dependency_assertion_confirmed",
        "dependency_assertion_edge_linked",
    ]


def test_source_revision_interruption_resumes_from_immutable_document_lineage(tmp_path: Path) -> None:
    service, document_id, item_id = _source_backed_service(tmp_path)
    service.register_authority_source(_authority_source())
    assertion = service.create_dependency_assertion(_quote_request(item_id=item_id, document_id=document_id))
    service.decide_dependency_assertion(
        assertion.id,
        DependencyAssertionDecisionRequest(by="reviewer-a", decision="confirmed"),
    )
    service._authority.set_operation_failure_injector(
        OperationFailureInjector(["after_authoritative_write_before_schedule"])
    )

    with pytest.raises(InjectedOperationFailure, match="after_authoritative_write_before_schedule"):
        service.ingest_source_document(
            "matter-documents",
            SourceDocumentIngestRequest(
                external_id="memo-1",
                filename="memo.txt",
                mime_type="text/plain",
                content="We rely on Regulation R section 12 after the authority update.",
            ),
        )
    operation = next(
        current
        for current in service.operation_store.list()
        if current.operation_type.value == "source_revision_reverify"
    )
    assert operation.status is OperationStatus.QUEUED
    assert service.get_dependency_assertion(assertion.id).needs_reverification is False

    service._authority.set_operation_failure_injector(OperationFailureInjector())
    recovered = service._authority.run_operation_once(worker_id="worker-restarted")
    assert recovered is not None
    assert recovered.status is OperationStatus.COMPLETED
    reverified = service.get_dependency_assertion(assertion.id)
    assert reverified.needs_reverification is True
    assert reverified.reverification_audit_id is not None


def test_worker_reconciles_source_revision_written_before_its_operation_record(tmp_path: Path) -> None:
    service, document_id, item_id = _source_backed_service(tmp_path)
    service.register_authority_source(_authority_source())
    assertion = service.create_dependency_assertion(_quote_request(item_id=item_id, document_id=document_id))
    service.decide_dependency_assertion(
        assertion.id,
        DependencyAssertionDecisionRequest(by="reviewer-a", decision="confirmed"),
    )
    source = service.document_store.get_document(document_id)
    replacement = service.document_store.write_document(
        SourceDocument(
            source_id=source.source_id,
            external_id=source.external_id,
            filename=source.filename,
            mime_type=source.mime_type,
            content="revised source written before durable operation scheduling",
        )
    )
    assert not any(current.target_resource_id == replacement.id for current in service.operation_store.list())

    batch = run_pending_operations(service, worker_id="source-gap-reconciler")

    assert batch.completed == 2
    assert service.get_dependency_assertion(assertion.id).needs_reverification is True


def test_governed_assertion_rest_and_python_sdk_surface(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal"))
    service = app.state.service
    _, document_id, item_id = _source_backed_service_for(service)
    service.register_authority_source(_authority_source())
    payload = _quote_request(item_id=item_id, document_id=document_id).model_dump(mode="json")

    async def exercise() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        transport = httpx.ASGITransport(app=app)
        async with AsyncSolomonClient(base_url="http://testserver", transport=transport) as client:
            created = await client.create_dependency_assertion(payload)
            inspected = await client.dependency_assertion(
                str(created["id"]), params={"matter_id": "matter-a", "client_id": "client-a"}
            )
            listed = await client.dependency_assertions(params={"matter_id": "matter-a", "client_id": "client-a"})
            decided = await client.decide_dependency_assertion(
                str(created["id"]),
                {"by": "reviewer-a", "decision": "confirmed", "expected_state_version": 1},
            )
            history = await client.dependency_assertion_history(str(created["id"]))
            commentary = _quote_request(item_id=item_id, document_id=document_id).model_copy(
                update={
                    "assertion_type": DependencyAssertionType.PROCEDURAL,
                    "evidence_kind": AssertionEvidenceKind.COMMENTARY,
                    "quote": None,
                    "quote_start": None,
                    "quote_end": None,
                    "commentary": "A separate operational assertion is retained for review.",
                    "idempotency_key": "rest-withdrawal",
                }
            )
            withdrawn = await client.withdraw_dependency_assertion(
                str((await client.create_dependency_assertion(commentary.model_dump(mode="json")))["id"]),
                {"by": "curator-a", "reason": "withdrawn before review", "expected_state_version": 1},
            )
        assert inspected["id"] == created["id"]
        assert withdrawn["decision"] == "withdrawn"
        return listed, decided, history

    listed, decided, history = asyncio.run(exercise())
    assert listed["items"][0]["source"] == "human"  # type: ignore[index]
    assert decided["source_suggestion_id"]
    assert history["edge"] is not None


def test_governed_assertion_rejects_conflicts_terminal_transitions_and_invalid_registered_sources(
    tmp_path: Path,
) -> None:
    service, document_id, item_id = _source_backed_service(tmp_path)
    service.register_authority_source(_authority_source())
    request = _quote_request(item_id=item_id, document_id=document_id)
    assertion = service.create_dependency_assertion(request)

    with pytest.raises(ConflictError, match="idempotency key"):
        service.create_dependency_assertion(request.model_copy(update={"rationale": "different"}))
    with pytest.raises(ConflictError, match="state version"):
        service.decide_dependency_assertion(
            assertion.id,
            DependencyAssertionDecisionRequest(by="reviewer-a", decision="confirmed", expected_state_version=2),
        )

    rejected = service.decide_dependency_assertion(
        assertion.id,
        DependencyAssertionDecisionRequest(by="reviewer-a", decision="rejected", reason="not adopted"),
    )
    assert not isinstance(rejected, DependencyEdge)
    assert rejected.decision is SuggestionDecision.REJECTED
    assert (
        service.decide_dependency_assertion(
            assertion.id,
            DependencyAssertionDecisionRequest(by="reviewer-a", decision="rejected", reason="not adopted"),
        ).id
        == assertion.id
    )
    with pytest.raises(BadRequestError, match="cannot be confirmed"):
        service.decide_dependency_assertion(
            assertion.id,
            DependencyAssertionDecisionRequest(by="reviewer-a", decision="confirmed"),
        )
    with pytest.raises(BadRequestError, match="require a traced"):
        service.decide_dependency_assertion(
            assertion.id,
            DependencyAssertionDecisionRequest(by="reviewer-a", decision="deferred", reason="late change"),
        )

    with pytest.raises(BadRequestError, match="traceable revision"):
        service.create_dependency_assertion(request.model_copy(update={"idempotency_key": "untraced-successor"}))
    replacement = service.create_dependency_assertion(
        request.model_copy(update={"idempotency_key": "traced-successor", "revision_of": assertion.id})
    )
    assert replacement.revision_of == assertion.id

    confirmed = service.create_dependency_assertion(
        request.model_copy(
            update={
                "assertion_type": DependencyAssertionType.PROCEDURAL,
                "evidence_kind": AssertionEvidenceKind.COMMENTARY,
                "quote": None,
                "quote_start": None,
                "quote_end": None,
                "commentary": "A distinct assertion must remain after confirmation.",
                "idempotency_key": "confirmed-withdrawal",
            }
        )
    )
    service.decide_dependency_assertion(
        confirmed.id, DependencyAssertionDecisionRequest(by="reviewer-a", decision="confirmed")
    )
    with pytest.raises(BadRequestError, match="cannot be withdrawn"):
        service.withdraw_dependency_assertion(
            confirmed.id, DependencyAssertionWithdrawRequest(by="curator-a", reason="must remain historical")
        )

    disabled = _authority_source().model_copy(update={"id": "disabled-gazette", "enabled": False})
    service.register_authority_source(disabled)
    with pytest.raises(BadRequestError, match="disabled"):
        service.create_dependency_assertion(
            request.model_copy(update={"authority_source_id": disabled.id, "idempotency_key": "disabled-source"})
        )
    out_of_scope = _authority_source().model_copy(update={"id": "bravo-gazette", "matter_id": "matter-b"})
    service.register_authority_source(out_of_scope)
    with pytest.raises(PolicyRefusalError, match="outside"):
        service.create_dependency_assertion(
            request.model_copy(
                update={"authority_source_id": out_of_scope.id, "idempotency_key": "out-of-scope-source"}
            )
        )


def test_governed_assertion_request_and_projection_reject_ambiguous_evidence_contracts(tmp_path: Path) -> None:
    service, document_id, item_id = _source_backed_service(tmp_path)
    service.register_authority_source(_authority_source())
    request = _quote_request(item_id=item_id, document_id=document_id)
    payload = request.model_dump(mode="json")

    with pytest.raises(ValueError, match="target requires"):
        DependencyAssertionCreateRequest.model_validate(
            {**payload, "authority_source_id": None, "authority_identifier": None}
        )
    with pytest.raises(ValueError, match="quote evidence requires"):
        DependencyAssertionCreateRequest.model_validate({**payload, "quote": None})
    with pytest.raises(ValueError, match="commentary evidence requires"):
        DependencyAssertionCreateRequest.model_validate(
            {**payload, "evidence_kind": "commentary", "commentary": "semantic observation"}
        )
    with pytest.raises(ValueError, match="trusted upstream"):
        DependencyAssertionCreateRequest.model_validate({**payload, "origin": "trusted_upstream"})

    assertion = service.create_dependency_assertion(request)
    persisted = assertion.model_dump(mode="json")
    with pytest.raises(ValueError, match="trusted upstream"):
        DependencySuggestion.model_validate({**persisted, "source": "trusted_upstream", "trusted_upstream_ref": None})
    with pytest.raises(ValueError, match="must equal"):
        DependencySuggestion.model_validate({**persisted, "source_span": "different quote"})
    with pytest.raises(ValueError, match="withdrawn assertions"):
        DependencySuggestion.model_validate({**persisted, "decision": "withdrawn"})


def test_mcp_inspects_scoped_confirmed_assertion_provenance_without_mutation(tmp_path: Path) -> None:
    service, document_id, item_id = _source_backed_service(tmp_path)
    service.register_authority_source(_authority_source())
    assertion = service.create_dependency_assertion(_quote_request(item_id=item_id, document_id=document_id))
    outcome = service.decide_dependency_assertion(
        assertion.id,
        DependencyAssertionDecisionRequest(by="reviewer-a", decision="confirmed"),
    )
    assert isinstance(outcome, DependencyEdge)
    runtime = SolomonMCPRuntime(service)

    inspected = runtime.dependency_suggestions(
        knowledge_item_id=item_id,
        decision="confirmed",
        matter_id="matter-a",
        client_id="client-a",
    )
    denied = runtime.dependency_suggestions(
        knowledge_item_id=item_id,
        decision="confirmed",
        matter_id="matter-b",
        client_id="client-b",
    )

    provenance = next(row for row in inspected["suggestions"] if row["id"] == assertion.id)
    assert provenance["source"] == "human"
    assert provenance["evidence_kind"] == "quote"
    assert provenance["edge_audit_id"] is not None
    assert denied["ok"] is False


def _source_backed_service_for(service: SolomonService) -> tuple[SolomonService, str, str]:
    document_id, item_id = _source_backed_item(service, matter_id="matter-a", client_id="client-a")
    return service, document_id, item_id


def _source_backed_service(tmp_path: Path) -> tuple[SolomonService, str, str]:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    document_id, item_id = _source_backed_item(service, matter_id="matter-a", client_id="client-a")
    return service, document_id, item_id


def _source_backed_item(service: SolomonService, *, matter_id: str, client_id: str) -> tuple[str, str]:
    source_id = "matter-documents"
    if not service.document_store.list_sources():
        service.register_document_source(
            DocumentSourceRequest(
                name="matter documents", kind=DocumentSourceKind.FILESYSTEM, root_ref="/matter-documents"
            )
        )
    source = service.document_store.list_sources()[0]
    if source.id != source_id:
        source = service.register_document_source(
            DocumentSourceRequest(
                source_id=source_id,
                name="matter documents",
                kind=DocumentSourceKind.FILESYSTEM,
                root_ref="/matter-documents",
            )
        )
    document, candidates = service.ingest_source_document(
        source.id,
        SourceDocumentIngestRequest(
            external_id="memo-1" if matter_id == "matter-a" else "memo-2",
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
            matter_id=matter_id,
            client_id=client_id,
        ),
    )
    return document.id, item.id


def _authority_source() -> AuthoritySource:
    return AuthoritySource(
        id="official-gazette",
        name="Official Gazette",
        kind=AuthoritySourceKind.FEED,
        root_ref="https://gazette.example.test/feed",
    )


def _quote_request(*, item_id: str, document_id: str) -> DependencyAssertionCreateRequest:
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
