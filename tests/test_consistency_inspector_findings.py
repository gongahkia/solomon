# SPDX-License-Identifier: Apache-2.0

"""Read-only inspector coverage for every unsafe projection state it must expose."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from solomon.consistency.inspection import ConsistencyInspector
from solomon.consistency.models import ConsistencyFindingCode, ConsistencyScope
from solomon.currency.models import now_utc
from solomon.graph.suggestions import SuggestionDecision
from solomon.operations.models import OperationScope, OperationStatus, OperationType


def _assertion(**updates: Any) -> Any:
    values: dict[str, Any] = {
        "id": "assertion-a",
        "item_id": "item-a",
        "decision": SuggestionDecision.CONFIRMED,
        "suggested_edge": SimpleNamespace(id="edge-a"),
        "source_document_id": "document-a",
        "source_document_version": 1,
        "source_document_sha256": "document-hash",
        "needs_reverification": False,
        "creation_audit_id": None,
        "review_audit_id": None,
        "edge_audit_id": None,
        "reverification_audit_id": None,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _operation(operation_type: OperationType, **updates: Any) -> Any:
    values: dict[str, Any] = {
        "id": f"operation-{operation_type.value}",
        "operation_type": operation_type,
        "status": OperationStatus.COMPLETED,
        "assertion_id": None,
        "suggestion_id": None,
        "source_resource_id": None,
        "target_resource_id": None,
        "payload": {},
        "audit_entry_hashes": [],
        "updated_at": now_utc(),
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _inspector(document_store: Any) -> ConsistencyInspector:
    service: Any = SimpleNamespace(document_store=document_store)
    return ConsistencyInspector(service)


def test_inspector_exposes_invalid_edge_provenance_and_duplicate_assertion_edges() -> None:
    inspector = _inspector(SimpleNamespace())
    assertions: list[Any] = [_assertion()]
    suggestions: list[Any] = []
    edges: list[Any] = [
        SimpleNamespace(id="unprovenanced", source_id="item-a", source_suggestion_id=None),
        SimpleNamespace(id="unknown", source_id="item-a", source_suggestion_id="outside-scope"),
        SimpleNamespace(id="edge-a", source_id="item-a", source_suggestion_id="assertion-a"),
        SimpleNamespace(id="edge-duplicate", source_id="item-a", source_suggestion_id="assertion-a"),
        SimpleNamespace(id="other-scope", source_id="item-b", source_suggestion_id=None),
    ]

    findings = inspector._edge_findings(assertions, suggestions, edges, {"item-a"})

    assert {finding.code for finding in findings} == {
        ConsistencyFindingCode.EDGE_INVALID_PROVENANCE,
        ConsistencyFindingCode.SCOPE_MISMATCH,
        ConsistencyFindingCode.DUPLICATE_ASSERTION_EDGE,
    }


def test_inspector_exposes_unreconstructible_sources_and_missing_reverification_operation() -> None:
    document = SimpleNamespace(
        id="document-a",
        source_id="source-a",
        version=1,
        content_sha256="document-hash",
        previous_version_id=None,
    )
    replacement = SimpleNamespace(id="document-b", source_id="source-a", previous_version_id="document-a")
    missing_store = SimpleNamespace(get_document=lambda _: (_ for _ in ()).throw(KeyError("missing")))
    missing = _inspector(missing_store)._source_findings([_assertion()], [])
    assert [finding.code for finding in missing] == [ConsistencyFindingCode.SOURCE_VERSION_UNRECONSTRUCTIBLE]

    mismatched_store = SimpleNamespace(
        get_document=lambda _: SimpleNamespace(**{**document.__dict__, "content_sha256": "changed"}),
        list_documents=lambda _: [],
    )
    mismatched = _inspector(mismatched_store)._source_findings([_assertion()], [])
    assert [finding.code for finding in mismatched] == [ConsistencyFindingCode.SOURCE_VERSION_UNRECONSTRUCTIBLE]

    revision_store = SimpleNamespace(get_document=lambda _: document, list_documents=lambda _: [document, replacement])
    missing_operation = _inspector(revision_store)._source_findings([_assertion()], [])
    assert [finding.code for finding in missing_operation] == [ConsistencyFindingCode.SOURCE_REVISION_OPERATION_MISSING]
    assert _inspector(revision_store)._valid_source_lineage(_assertion()) is True
    assert _inspector(missing_store)._valid_source_lineage(_assertion()) is False
    assert _inspector(revision_store)._valid_source_lineage(_assertion(source_document_id=None)) is False


def test_inspector_exposes_stuck_and_completed_operations_missing_each_expected_projection() -> None:
    candidate_store = SimpleNamespace(
        get_candidate=lambda _: (_ for _ in ()).throw(KeyError("missing candidate"))
    )
    inspector = _inspector(candidate_store)
    confirmed: list[Any] = [_assertion(needs_reverification=False)]
    suggestions: list[Any] = [
        SimpleNamespace(
            id="suggestion-a",
            decision=SuggestionDecision.PENDING,
            suggested_edge=SimpleNamespace(id="edge-s"),
        )
    ]
    old = now_utc() - timedelta(minutes=20)
    operations: list[Any] = [
        _operation(
            OperationType.ASSERTION_CONFIRM,
            id="stuck-confirm",
            status=OperationStatus.QUEUED,
            assertion_id="assertion-a",
            updated_at=old,
        ),
        _operation(OperationType.ASSERTION_CONFIRM, id="completed-confirm", assertion_id="assertion-a"),
        _operation(OperationType.ASSERTION_CREATE, id="completed-create", assertion_id="assertion-a"),
        _operation(OperationType.SUGGESTION_CONFIRM, id="completed-suggestion", suggestion_id="suggestion-a"),
        _operation(
            OperationType.CANDIDATE_PROMOTION,
            id="completed-candidate",
            source_resource_id="candidate-a",
            target_resource_id="item-a",
        ),
        _operation(OperationType.SOURCE_REVISION_REVERIFY, id="completed-reverify", assertion_id="assertion-a"),
    ]

    findings = inspector._operation_findings(
        confirmed,
        suggestions,
        [],
        operations,
        now_utc(),
        timedelta(minutes=15),
    )

    assert {finding.code for finding in findings} == {
        ConsistencyFindingCode.OPERATION_STUCK,
        ConsistencyFindingCode.COMPLETED_PROJECTION_MISSING,
    }
    missing = [
        finding for finding in findings if finding.code is ConsistencyFindingCode.COMPLETED_PROJECTION_MISSING
    ]
    assert len(missing) == 5


def test_inspector_exposes_missing_audit_links_unknown_operations_and_missing_edges() -> None:
    inspector = _inspector(SimpleNamespace())
    assertion: list[Any] = [_assertion(creation_audit_id="missing-assertion-audit")]
    operation: list[Any] = [
        _operation(
            OperationType.ASSERTION_CONFIRM,
            id="operation-a",
            assertion_id="assertion-a",
            audit_entry_hashes=["missing-operation-audit"],
        )
    ]
    entries: list[Any] = [
        SimpleNamespace(
            entry_hash="event-a",
            payload={
                "assertion_id": "assertion-a",
                "operation_id": "unknown-operation:audit",
                "edge_id": "edge-missing",
            },
        ),
        SimpleNamespace(entry_hash="outside", payload={"assertion_id": "other", "operation_id": "unknown"}),
    ]

    findings = inspector._audit_findings(assertion, [], operation, entries)

    assert {finding.code for finding in findings} == {
        ConsistencyFindingCode.AUDIT_REFERENCE_MISSING,
        ConsistencyFindingCode.UNKNOWN_OPERATION_PROJECTION,
    }


def test_inspector_selects_only_exact_or_scope_derived_operations() -> None:
    scope = ConsistencyScope(tenant_id="tenant-a", matter_id="matter-a", client_id="client-a")
    exact = OperationScope(tenant_id="tenant-a", matter_id="matter-a", client_id="client-a")
    other_scope = OperationScope(tenant_id="tenant-a", matter_id="matter-other", client_id="client-other")
    operations: list[Any] = [
        SimpleNamespace(id="other-tenant", scope=OperationScope(tenant_id="tenant-other")),
        SimpleNamespace(id="exact", scope=exact),
        SimpleNamespace(
            id="evidence",
            scope=other_scope,
            operation_type=OperationType.EVIDENCE_INGESTION,
            target_resource_id="document-a",
            assertion_id=None,
        ),
        SimpleNamespace(
            id="suggestions",
            scope=other_scope,
            operation_type=OperationType.SUGGESTION_GENERATION,
            target_resource_id="item-a",
            assertion_id=None,
        ),
        SimpleNamespace(
            id="assertion",
            scope=other_scope,
            operation_type=OperationType.ASSERTION_CONFIRM,
            target_resource_id=None,
            assertion_id="assertion-a",
        ),
        SimpleNamespace(
            id="excluded",
            scope=other_scope,
            operation_type=OperationType.SUGGESTION_GENERATION,
            target_resource_id="item-other",
            assertion_id=None,
        ),
    ]
    service: Any = SimpleNamespace(operation_store=SimpleNamespace(list=lambda **_: operations))
    inspector = ConsistencyInspector(service)

    selected = inspector._operations(
        scope,
        item_ids={"item-a"},
        assertions=[_assertion()],
        source_documents=[SimpleNamespace(id="document-a")],
    )

    assert [operation.id for operation in selected] == ["exact", "evidence", "suggestions", "assertion"]
