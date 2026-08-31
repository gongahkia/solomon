# SPDX-License-Identifier: Apache-2.0

"""Vendor-neutral, headless crash-consistency proof against real mixed persistence."""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from solomon.api.service import (
    AuthorityChangeRequest,
    CandidateClaimPromotionRequest,
    DependencyAssertionCreateRequest,
    DependencyAssertionDecisionRequest,
    DependencyAssertionWithdrawRequest,
    DocumentSourceRequest,
    SolomonService,
    SourceDocumentIngestRequest,
)
from solomon.audit.journal import AuditJournal
from solomon.consistency.models import ConsistencyFindingCode, ConsistencyScope, RepairPlan
from solomon.contracts import AuthoritySource, AuthoritySourceKind
from solomon.currency.models import CurrencyState, KnowledgeKind, SourceKind
from solomon.errors import BadRequestError
from solomon.graph.models import DependencyEdge
from solomon.graph.suggestions import (
    AssertionEvidenceKind,
    DependencyAssertionType,
    DependencySuggestion,
    SuggestionDecision,
)
from solomon.operations.failure_injection import InjectedOperationFailure, OperationFailureInjector
from solomon.operations.models import OperationRecord, OperationScope, OperationStatus, OperationType
from solomon.sources.models import DocumentSourceKind, SourceDocument
from solomon.store.postgres import PostgresDependencyError
from solomon.worker import run_pending_operations

pytestmark = pytest.mark.integration

CHANGE_AT = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
_QUOTE = "We rely on Regulation R section 12."


def test_headless_crash_consistency_scenario_has_repeatable_semantics(tmp_path: Path) -> None:
    dsn = os.environ.get("SOLOMON_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set SOLOMON_TEST_POSTGRES_DSN to run the real PostgreSQL crash-consistency proof")
    psycopg = pytest.importorskip("psycopg")
    schemas = [f"proof_{uuid.uuid4().hex}", f"proof_{uuid.uuid4().hex}"]
    results: list[dict[str, object]] = []
    try:
        for index, schema in enumerate(schemas):
            results.append(_run_scenario(dsn=dsn, schema=schema, root=tmp_path / f"run-{index}"))
    except PostgresDependencyError as exc:
        pytest.skip(str(exc))
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            for schema in schemas:
                conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')

    assert results[0] == results[1]


def _run_scenario(*, dsn: str, schema: str, root: Path) -> dict[str, object]:
    services: list[SolomonService] = []
    try:
        first = _service(dsn=dsn, schema=schema, root=root)
        services.append(first)
        source_a, document_a, item_a = _source_backed_item(first, scope="a")
        source_b, document_b, item_b = _source_backed_item(first, scope="b")
        first.register_authority_source(
            AuthoritySource(
                id="official-gazette",
                name="Official Gazette",
                kind=AuthoritySourceKind.FEED,
                root_ref="https://gazette.example.test/feed",
            )
        )

        assertion_a = _quote_assertion(first, item_a, document_a.id, "normal-a", "SG-R-12")
        edge_a = first.decide_dependency_assertion(
            assertion_a.id,
            DependencyAssertionDecisionRequest(by="reviewer-a", decision="confirmed", reason="normal proof"),
        )
        assert isinstance(edge_a, DependencyEdge)
        assert edge_a.source_suggestion_id == assertion_a.id
        assert first.store.get_item(item_a).currency_state is CurrencyState.LIVE

        assertion_b = _quote_assertion(first, item_b, document_b.id, "edge-crash-b", "SG-R-12")
        first._authority.set_operation_failure_injector(OperationFailureInjector(["after_graph_edge_before_ack"]))
        with pytest.raises(BadRequestError, match="durably queued"):
            first.decide_dependency_assertion(
                assertion_b.id,
                DependencyAssertionDecisionRequest(by="reviewer-b", decision="confirmed", reason="edge crash proof"),
            )
        edge_operation = _operation(first, OperationType.ASSERTION_CONFIRM, assertion_b.id)
        assert edge_operation.status is OperationStatus.RETRYING
        assert _edges_for_assertion(first, item_b, assertion_b.id) == [assertion_b.suggested_edge.id]
        assert first.get_dependency_assertion(assertion_b.id).decision is SuggestionDecision.PENDING

        _close(first)
        services.remove(first)
        restarted = _service(dsn=dsn, schema=schema, root=root)
        services.append(restarted)
        assert edge_operation.next_eligible_retry_at is not None
        recovered_edge = restarted._authority.run_operation_once(
            worker_id="restart-after-edge", now=edge_operation.next_eligible_retry_at
        )
        assert recovered_edge is not None and recovered_edge.status is OperationStatus.COMPLETED
        assert _edges_for_assertion(restarted, item_b, assertion_b.id) == [assertion_b.suggested_edge.id]

        restarted._authority.set_operation_failure_injector(OperationFailureInjector(["during_currency_propagation"]))
        with pytest.raises(BadRequestError, match="durably queued"):
            restarted.register_authority_change(
                assertion_a.suggested_edge.target_id,
                _authority_change_request(),
            )
        currency_operation = _operation(restarted, OperationType.AUTHORITY_CHANGE_PROPAGATION)
        assert currency_operation.status is OperationStatus.RETRYING

        _close(restarted)
        services.remove(restarted)
        resumed = _service(dsn=dsn, schema=schema, root=root)
        services.append(resumed)
        assert currency_operation.next_eligible_retry_at is not None
        recovered_currency = resumed._authority.run_operation_once(
            worker_id="restart-after-currency", now=currency_operation.next_eligible_retry_at
        )
        assert recovered_currency is not None and recovered_currency.status is OperationStatus.COMPLETED
        resumed.register_authority_change(assertion_a.suggested_edge.target_id, _authority_change_request())
        assert len(
            [
                operation
                for operation in resumed.operation_store.list()
                if operation.operation_type is OperationType.AUTHORITY_CHANGE_PROPAGATION
            ]
        ) == 1
        for item_id in (item_a, item_b):
            item = resumed.store.get_item(item_id)
            assert item.currency_state is CurrencyState.STALE_PENDING_REVERIFICATION
            reasons = item.metadata.get("staleness_reasons", [])
            assert (
                sum(
                    isinstance(reason, dict) and reason.get("change_id") == currency_operation.id
                    for reason in reasons
                )
                == 1
            )

        assertion_c = _quote_assertion(resumed, item_a, document_a.id, "concurrent-c", "SG-R-13")
        concurrent_operation, _ = resumed.operation_store.create(
            OperationRecord(
                operation_type=OperationType.ASSERTION_CONFIRM,
                scope=OperationScope(tenant_id="tenant-proof", matter_id="matter-a", client_id="client-a"),
                actor_id="reviewer-c",
                authorization_context={"service_access": "review", "actor_type": "reviewer"},
                correlation_id=assertion_c.audit_correlation_id or "concurrent-c",
                causation_id=assertion_c.id,
                idempotency_key=f"concurrent-confirm:{assertion_c.id}",
                source_resource_id=assertion_c.source_document_id,
                source_version=assertion_c.source_document_version,
                target_resource_id=assertion_c.suggested_edge.target_id,
                assertion_id=assertion_c.id,
                requested_transition="confirmed",
                payload={"expected_state_version": assertion_c.state_version},
            )
        )
        _commit_read_transactions(resumed)
        second_worker = _service(dsn=dsn, schema=schema, root=root)
        services.append(second_worker)
        with ThreadPoolExecutor(max_workers=2) as executor:
            projected = list(
                executor.map(
                    lambda pair: pair[0]._authority.run_operation_once(worker_id=pair[1]),
                    ((resumed, "concurrent-worker-a"), (second_worker, "concurrent-worker-b")),
                )
            )
        assert sum(operation is not None for operation in projected) == 1
        assert resumed.operation_store.get(concurrent_operation.id).status is OperationStatus.COMPLETED
        assert _edges_for_assertion(resumed, item_a, assertion_c.id) == [assertion_c.suggested_edge.id]

        resumed._authority.set_operation_failure_injector(
            OperationFailureInjector(["after_assertion_authoritative_write_before_schedule"])
        )
        with pytest.raises(InjectedOperationFailure, match="after_assertion_authoritative_write_before_schedule"):
            _commentary_assertion(resumed, item_b, document_b.id, "pending-no-edge", "SG-R-14")
        pending = next(
            assertion
            for assertion in resumed.dependency_assertions(matter_id="matter-b", client_id="client-b")
            if assertion.idempotency_key == "pending-no-edge"
        )
        resumed._authority.set_operation_failure_injector(OperationFailureInjector())
        run_pending_operations(resumed, worker_id="pending-assertion-reconciler")
        assert _edges_for_assertion(resumed, item_b, pending.id) == []

        rejected = _commentary_assertion(resumed, item_b, document_b.id, "rejected-no-edge", "SG-R-15")
        resumed.decide_dependency_assertion(
            rejected.id,
            DependencyAssertionDecisionRequest(by="reviewer-b", decision="rejected", reason="not approved"),
        )
        deferred = _commentary_assertion(resumed, item_b, document_b.id, "deferred-no-edge", "SG-R-16")
        resumed.decide_dependency_assertion(
            deferred.id,
            DependencyAssertionDecisionRequest(by="reviewer-b", decision="deferred", reason="needs evidence"),
        )
        withdrawn = _commentary_assertion(resumed, item_b, document_b.id, "withdrawn-no-edge", "SG-R-17")
        resumed.withdraw_dependency_assertion(
            withdrawn.id,
            DependencyAssertionWithdrawRequest(by="curator-b", reason="withdrawn before review"),
        )
        assert all(
            _edges_for_assertion(resumed, item_b, assertion.id) == []
            for assertion in (rejected, deferred, withdrawn)
        )

        resumed._authority.set_operation_failure_injector(
            OperationFailureInjector(["after_source_revision_authoritative_write_before_schedule"])
        )
        with pytest.raises(InjectedOperationFailure, match="after_source_revision_authoritative_write_before_schedule"):
            resumed.ingest_source_document(
                source_b,
                SourceDocumentIngestRequest(
                    external_id="memo-b",
                    filename="memo-b.txt",
                    mime_type="text/plain",
                    content="We rely on Regulation R section 12 after the source revision.",
                ),
            )
        resumed._authority.set_operation_failure_injector(OperationFailureInjector())
        run_pending_operations(resumed, worker_id="source-revision-reconciler")
        assert resumed.get_dependency_assertion(assertion_b.id).needs_reverification is True

        _delete_edge(resumed, edge_a.id)
        report = resumed.consistency_check(matter_id="matter-a", client_id="client-a")
        assert ConsistencyFindingCode.CONFIRMED_ASSERTION_MISSING_EDGE in {finding.code for finding in report.findings}
        dry_plan = resumed.consistency_repair_plan(matter_id="matter-a", client_id="client-a")
        assert dry_plan == resumed.consistency_repair_plan(matter_id="matter-a", client_id="client-a")
        assert _edges_for_assertion(resumed, item_a, assertion_a.id) == []
        repaired = resumed.apply_consistency_repair(dry_plan)
        assert repaired.applied is True
        assert _edges_for_assertion(resumed, item_a, assertion_a.id) == [edge_a.id]

        edge_c = assertion_c.suggested_edge
        _delete_edge(resumed, edge_c.id)
        stale_plan = resumed.consistency_repair_plan(matter_id="matter-a", client_id="client-a")
        current_c = resumed.get_dependency_assertion(assertion_c.id)
        resumed.graph.update_dependency_suggestion(
            current_c.model_copy(update={"state_version": current_c.state_version + 1})
        )
        stale = resumed.apply_consistency_repair(stale_plan)
        assert stale.applied is False
        assert stale.refusal == "repair plan is stale because scoped consistency state changed"
        fresh_plan = resumed.consistency_repair_plan(matter_id="matter-a", client_id="client-a")
        assert resumed.apply_consistency_repair(fresh_plan).applied is True

        resumed.graph.add_dependency(
            rejected.suggested_edge.model_copy(update={"source_suggestion_id": rejected.id, "created_by": "proof"})
        )
        ambiguous_report = resumed.consistency_check(matter_id="matter-b", client_id="client-b")
        assert ConsistencyFindingCode.EDGE_INVALID_PROVENANCE in {finding.code for finding in ambiguous_report.findings}
        ambiguous_plan = resumed.consistency_repair_plan(matter_id="matter-b", client_id="client-b")
        assert all(action.assertion_id != rejected.id for action in ambiguous_plan.actions)
        cross_tenant_plan = RepairPlan.create(
            scope=ConsistencyScope(tenant_id="other-tenant", matter_id="matter-a", client_id="client-a"),
            report_fingerprint=dry_plan.report_fingerprint,
            actions=dry_plan.actions,
        )
        assert resumed.apply_consistency_repair(cross_tenant_plan).applied is False

        persisted_document = resumed.document_store.get_document(document_a.id)
        assert persisted_document.content_sha256 == assertion_a.source_document_sha256
        assertion_history = resumed.dependency_assertion_history(
            assertion_a.id, matter_id="matter-a", client_id="client-a"
        )
        assert {entry["event_type"] for entry in assertion_history["audit_entries"]} >= {
            "dependency_assertion_created",
            "dependency_assertion_confirmed",
            "dependency_assertion_edge_linked",
        }
        assert any(entry.event_type == "consistency_repair_applied" for entry in resumed.audit.list_entries())
        pack = resumed.export_audit_pack(root / "audit-pack")
        assert AuditJournal.verify_pack(pack).ok is True

        return {
            "assertion_statuses": sorted(
                assertion.decision.value
                for assertion in resumed.dependency_assertions(limit=10_000)
            ),
            "operation_statuses": sorted(
                (operation.operation_type.value, operation.status.value)
                for operation in resumed.operation_store.list(limit=10_000)
            ),
            "scope_a_edges": len(resumed.graph.get_dependencies(item_a)),
            "scope_b_invalid_findings": sorted(finding.code.value for finding in ambiguous_report.findings),
            "currency_states": [
                resumed.store.get_item(item_a).currency_state.value,
                resumed.store.get_item(item_b).currency_state.value,
            ],
            "audit_pack_ok": AuditJournal.verify_pack(pack).ok,
        }
    finally:
        for service in services:
            _close(service)


def _service(*, dsn: str, schema: str, root: Path) -> SolomonService:
    return SolomonService(
        data_dir=root / "data",
        journal_dir=root / "journal",
        database_url=dsn,
        postgres_schema=schema,
        tenant_id="tenant-proof",
    )


def _source_backed_item(service: SolomonService, *, scope: str) -> tuple[str, SourceDocument, str]:
    source = service.register_document_source(
        DocumentSourceRequest(
            source_id=f"source-{scope}",
            name=f"source {scope}",
            kind=DocumentSourceKind.FILESYSTEM,
            root_ref=f"/source-{scope}",
        )
    )
    document, candidates = service.ingest_source_document(
        source.id,
        SourceDocumentIngestRequest(
            external_id=f"memo-{scope}",
            filename=f"memo-{scope}.txt",
            mime_type="text/plain",
            content="We rely on Regulation R section 12. The conclusion applies to the operating rule.",
        ),
    )
    item = service.promote_candidate_claim(
        candidates[0].id,
        CandidateClaimPromotionRequest(
            by=f"curator-{scope}",
            kind=KnowledgeKind.POSITION,
            source_kind=SourceKind.MATTER_DOC,
            matter_id=f"matter-{scope}",
            client_id=f"client-{scope}",
        ),
    )
    return source.id, document, item.id


def _quote_assertion(
    service: SolomonService,
    item_id: str,
    document_id: str,
    key: str,
    identifier: str,
) -> DependencySuggestion:
    return service.create_dependency_assertion(
        DependencyAssertionCreateRequest(
            item_id=item_id,
            source_document_id=document_id,
            source_document_version=1,
            target_kind="external_authority",
            authority_source_id="official-gazette",
            authority_identifier=identifier,
            assertion_type=DependencyAssertionType.NORMATIVE_POLICY,
            evidence_kind=AssertionEvidenceKind.QUOTE,
            quote=_QUOTE,
            quote_start=0,
            quote_end=len(_QUOTE),
            rationale="headless crash consistency proof",
            created_by="curator-a" if "a" in key else "curator-b",
            idempotency_key=key,
        )
    )


def _commentary_assertion(
    service: SolomonService,
    item_id: str,
    document_id: str,
    key: str,
    identifier: str,
) -> DependencySuggestion:
    return service.create_dependency_assertion(
        DependencyAssertionCreateRequest(
            item_id=item_id,
            source_document_id=document_id,
            source_document_version=1,
            target_kind="external_authority",
            authority_source_id="official-gazette",
            authority_identifier=identifier,
            assertion_type=DependencyAssertionType.PROCEDURAL,
            evidence_kind=AssertionEvidenceKind.COMMENTARY,
            commentary=f"review-only {key}",
            rationale="headless crash consistency proof",
            created_by="curator-b",
            idempotency_key=key,
        )
    )


def _authority_change_request() -> AuthorityChangeRequest:
    return AuthorityChangeRequest(new_version="v2", changed_at=CHANGE_AT.isoformat())


def _operation(
    service: SolomonService,
    operation_type: OperationType,
    assertion_id: str | None = None,
) -> OperationRecord:
    return cast(
        OperationRecord,
        next(
            operation
            for operation in service.operation_store.list(limit=10_000)
            if operation.operation_type is operation_type
            and (assertion_id is None or operation.assertion_id == assertion_id)
        ),
    )


def _edges_for_assertion(service: SolomonService, item_id: str, assertion_id: str) -> list[str]:
    return [
        edge.id
        for edge in service.graph.get_dependencies(item_id)
        if edge.source_suggestion_id == assertion_id
    ]


def _delete_edge(service: SolomonService, edge_id: str) -> None:
    graph = cast(Any, service.graph)
    with graph._transaction():
        graph._execute(
            f"DELETE FROM {graph._table('dependency_edges')} WHERE edge_id = %s",  # noqa: S608 -- fixed internal table
            (edge_id,),
        )


def _close(service: SolomonService) -> None:
    service.operation_store.close()
    service.store.close()
    service.graph.close()
    service.index.close()


def _commit_read_transactions(service: SolomonService) -> None:
    """Release psycopg's implicit read transactions before a second service runs migrations."""

    for component in (service.operation_store, service.store, service.graph, service.index):
        connection = getattr(component, "_conn", None)
        if connection is not None:
            connection.commit()
