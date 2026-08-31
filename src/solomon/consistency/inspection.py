# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast

from solomon.consistency.models import (
    ConsistencyFinding,
    ConsistencyFindingCode,
    ConsistencyReport,
    ConsistencyScope,
)
from solomon.currency.models import now_utc
from solomon.graph.propagation import CurrencyPropagator
from solomon.graph.suggestions import DependencySuggestion, SuggestionDecision
from solomon.operations.models import OperationRecord, OperationScope, OperationStatus, OperationType


class ConsistencyInspector:
    """Read-only, exact-scope detection for durable-operation projections."""

    def __init__(self, service: Any) -> None:
        self._service = service

    def check(
        self,
        scope: ConsistencyScope,
        *,
        stuck_after: timedelta = timedelta(minutes=15),
        now: datetime | None = None,
    ) -> ConsistencyReport:
        if stuck_after.total_seconds() <= 0:
            raise ValueError("stuck threshold must be positive")
        timestamp = now or now_utc()
        items = self._service.store.get_many(matter_id=scope.matter_id, client_id=scope.client_id)
        item_ids = {item.id for item in items}
        assertions = self._assertions(scope)
        edges = self._service.graph.subgraph_for_scope(
            store=self._service.store,
            matter_id=scope.matter_id,
            client_id=scope.client_id,
        )
        operations = self._operations(scope)
        findings: list[ConsistencyFinding] = []
        findings.extend(self._assertion_findings(assertions, edges))
        findings.extend(self._edge_findings(assertions, edges, item_ids))
        findings.extend(self._source_findings(assertions, operations))
        findings.extend(self._operation_findings(assertions, edges, operations, timestamp, stuck_after))
        findings.extend(self._currency_findings(scope, items))
        findings.extend(self._audit_findings(assertions, edges, operations))
        return ConsistencyReport.create(
            scope=scope,
            findings=_deduplicate(findings),
            observed_state={
                "items": [item.model_dump(mode="json") for item in items],
                "assertions": [assertion.model_dump(mode="json") for assertion in assertions],
                "edges": [edge.model_dump(mode="json") for edge in edges],
                "operations": [operation.model_dump(mode="json") for operation in operations],
            },
        )

    def _assertions(self, scope: ConsistencyScope) -> list[DependencySuggestion]:
        return cast(
            list[DependencySuggestion],
            self._service.dependency_assertions(
                matter_id=scope.matter_id,
                client_id=scope.client_id,
                limit=10_000,
            ),
        )

    def _operations(self, scope: ConsistencyScope) -> list[OperationRecord]:
        return cast(
            list[OperationRecord],
            self._service.operation_store.list(
                scope=OperationScope(tenant_id=scope.tenant_id, matter_id=scope.matter_id, client_id=scope.client_id),
                limit=10_000,
            ),
        )

    def _assertion_findings(self, assertions: list[DependencySuggestion], edges: list[Any]) -> list[ConsistencyFinding]:
        edge_ids = {edge.id for edge in edges}
        findings: list[ConsistencyFinding] = []
        for assertion in assertions:
            if assertion.decision is not SuggestionDecision.CONFIRMED:
                continue
            if assertion.suggested_edge.id not in edge_ids:
                findings.append(
                    ConsistencyFinding(
                        code=ConsistencyFindingCode.CONFIRMED_ASSERTION_MISSING_EDGE,
                        resource_type="dependency_assertion",
                        resource_id=assertion.id,
                        related_ids=[assertion.suggested_edge.id],
                        repairable=self._valid_source_lineage(assertion),
                        detail="confirmed assertion has no persisted graph edge",
                    )
                )
        return findings

    def _edge_findings(
        self,
        assertions: list[DependencySuggestion],
        edges: list[Any],
        item_ids: set[str],
    ) -> list[ConsistencyFinding]:
        indexed = {assertion.id: assertion for assertion in assertions}
        by_assertion: dict[str, list[Any]] = {}
        findings: list[ConsistencyFinding] = []
        for edge in edges:
            if edge.source_id not in item_ids:
                continue
            if edge.source_suggestion_id is None:
                findings.append(
                    ConsistencyFinding(
                        code=ConsistencyFindingCode.EDGE_INVALID_PROVENANCE,
                        resource_type="dependency_edge",
                        resource_id=edge.id,
                        detail="graph edge has no originating assertion provenance",
                    )
                )
                continue
            assertion = indexed.get(edge.source_suggestion_id)
            if assertion is None:
                findings.append(
                    ConsistencyFinding(
                        code=ConsistencyFindingCode.SCOPE_MISMATCH,
                        resource_type="dependency_edge",
                        resource_id=edge.id,
                        detail="graph edge provenance does not resolve in the requested scope",
                    )
                )
                continue
            by_assertion.setdefault(assertion.id, []).append(edge)
            if assertion.decision is not SuggestionDecision.CONFIRMED or assertion.suggested_edge.id != edge.id:
                findings.append(
                    ConsistencyFinding(
                        code=ConsistencyFindingCode.EDGE_INVALID_PROVENANCE,
                        resource_type="dependency_edge",
                        resource_id=edge.id,
                        related_ids=[assertion.id],
                        detail="graph edge does not match a valid confirmed assertion",
                    )
                )
        for assertion_id, linked_edges in by_assertion.items():
            if len(linked_edges) > 1:
                findings.append(
                    ConsistencyFinding(
                        code=ConsistencyFindingCode.DUPLICATE_ASSERTION_EDGE,
                        resource_type="dependency_assertion",
                        resource_id=assertion_id,
                        related_ids=sorted(edge.id for edge in linked_edges),
                        detail="more than one graph edge carries the same assertion provenance",
                    )
                )
        return findings

    def _source_findings(
        self,
        assertions: list[DependencySuggestion],
        operations: list[OperationRecord],
    ) -> list[ConsistencyFinding]:
        findings: list[ConsistencyFinding] = []
        operation_keys = {
            (operation.assertion_id, operation.source_resource_id, operation.target_resource_id)
            for operation in operations
            if operation.operation_type is OperationType.SOURCE_REVISION_REVERIFY
        }
        for assertion in assertions:
            if assertion.source_document_id is None:
                continue
            try:
                document = self._service.document_store.get_document(assertion.source_document_id)
            except Exception:
                findings.append(
                    ConsistencyFinding(
                        code=ConsistencyFindingCode.SOURCE_VERSION_UNRECONSTRUCTIBLE,
                        resource_type="dependency_assertion",
                        resource_id=assertion.id,
                        detail="assertion source document version cannot be reconstructed",
                    )
                )
                continue
            if (
                document.version != assertion.source_document_version
                or document.content_sha256 != assertion.source_document_sha256
            ):
                findings.append(
                    ConsistencyFinding(
                        code=ConsistencyFindingCode.SOURCE_VERSION_UNRECONSTRUCTIBLE,
                        resource_type="dependency_assertion",
                        resource_id=assertion.id,
                        related_ids=[document.id],
                        detail="assertion source document does not match recorded version or hash",
                    )
                )
                continue
            replacements = [
                candidate
                for candidate in self._service.document_store.list_documents(document.source_id)
                if candidate.previous_version_id == document.id
            ]
            for replacement in replacements:
                key = (assertion.id, document.id, replacement.id)
                if not assertion.needs_reverification and key not in operation_keys:
                    findings.append(
                        ConsistencyFinding(
                            code=ConsistencyFindingCode.SOURCE_REVISION_OPERATION_MISSING,
                            resource_type="dependency_assertion",
                            resource_id=assertion.id,
                            related_ids=[document.id, replacement.id],
                            repairable=True,
                            detail="source revision exists without a durable reverification operation",
                        )
                    )
        return findings

    def _operation_findings(
        self,
        assertions: list[DependencySuggestion],
        edges: list[Any],
        operations: list[OperationRecord],
        now: datetime,
        stuck_after: timedelta,
    ) -> list[ConsistencyFinding]:
        findings: list[ConsistencyFinding] = []
        assertion_by_id = {assertion.id: assertion for assertion in assertions}
        edge_ids = {edge.id for edge in edges}
        for operation in operations:
            if operation.status in {OperationStatus.QUEUED, OperationStatus.CLAIMED, OperationStatus.RETRYING}:
                if now - operation.updated_at > stuck_after:
                    findings.append(
                        ConsistencyFinding(
                            code=ConsistencyFindingCode.OPERATION_STUCK,
                            resource_type="knowledge_operation",
                            resource_id=operation.id,
                            detail="operation has exceeded the configured pending threshold",
                        )
                    )
            if operation.status is not OperationStatus.COMPLETED:
                continue
            assertion = assertion_by_id.get(operation.assertion_id or "")
            if operation.operation_type is OperationType.ASSERTION_CONFIRM and (
                assertion is None or assertion.suggested_edge.id not in edge_ids
            ):
                findings.append(
                    ConsistencyFinding(
                        code=ConsistencyFindingCode.COMPLETED_PROJECTION_MISSING,
                        resource_type="knowledge_operation",
                        resource_id=operation.id,
                        related_ids=[operation.assertion_id] if operation.assertion_id else [],
                        detail="completed assertion confirmation has no expected graph projection",
                    )
                )
            if operation.operation_type is OperationType.SOURCE_REVISION_REVERIFY and (
                assertion is None or not assertion.needs_reverification
            ):
                findings.append(
                    ConsistencyFinding(
                        code=ConsistencyFindingCode.COMPLETED_PROJECTION_MISSING,
                        resource_type="knowledge_operation",
                        resource_id=operation.id,
                        related_ids=[operation.assertion_id] if operation.assertion_id else [],
                        detail="completed source revision operation has no reverification marker",
                    )
                )
        return findings

    def _currency_findings(self, scope: ConsistencyScope, items: list[Any]) -> list[ConsistencyFinding]:
        item_ids = {item.id for item in items}
        operations = self._service.operation_store.list(limit=10_000)
        findings: list[ConsistencyFinding] = []
        for operation in operations:
            if operation.operation_type is not OperationType.AUTHORITY_CHANGE_PROPAGATION:
                continue
            if operation.status is not OperationStatus.COMPLETED or operation.target_resource_id is None:
                continue
            change_id = operation.payload.get("change_id")
            if not isinstance(change_id, str):
                change_id = operation.id
            impact = CurrencyPropagator(graph=self._service.graph, store=self._service.store).impact_query(
                operation.target_resource_id
            )
            for item_id in impact.stale_item_ids:
                if item_id not in item_ids:
                    continue
                item = self._service.store.get_item(item_id)
                reasons = item.metadata.get("staleness_reasons", [])
                recorded = any(isinstance(reason, dict) and reason.get("change_id") == change_id for reason in reasons)
                if not recorded:
                    findings.append(
                        ConsistencyFinding(
                            code=ConsistencyFindingCode.CURRENCY_PROJECTION_STALE,
                            resource_type="knowledge_item",
                            resource_id=item.id,
                            related_ids=[operation.id],
                            detail="completed authority change has no matching currency propagation marker",
                        )
                    )
        return findings

    def _audit_findings(
        self,
        assertions: list[DependencySuggestion],
        edges: list[Any],
        operations: list[OperationRecord],
    ) -> list[ConsistencyFinding]:
        entries = self._service.audit.list_entries()
        by_hash = {entry.entry_hash for entry in entries}
        assertion_ids = {assertion.id for assertion in assertions}
        edge_ids = {edge.id for edge in edges}
        operation_ids = {operation.id for operation in operations}
        findings: list[ConsistencyFinding] = []
        for assertion in assertions:
            for audit_hash in (assertion.creation_audit_id, assertion.review_audit_id, assertion.edge_audit_id):
                if audit_hash is not None and audit_hash not in by_hash:
                    findings.append(
                        ConsistencyFinding(
                            code=ConsistencyFindingCode.AUDIT_REFERENCE_MISSING,
                            resource_type="dependency_assertion",
                            resource_id=assertion.id,
                            detail="assertion references an audit event that is absent",
                        )
                    )
        for operation in operations:
            for audit_hash in operation.audit_entry_hashes:
                if audit_hash not in by_hash:
                    findings.append(
                        ConsistencyFinding(
                            code=ConsistencyFindingCode.AUDIT_REFERENCE_MISSING,
                            resource_type="knowledge_operation",
                            resource_id=operation.id,
                            detail="operation references an audit event that is absent",
                        )
                    )
        for entry in entries:
            assertion_id = entry.payload.get("assertion_id")
            if assertion_id not in assertion_ids:
                continue
            operation_id = entry.payload.get("operation_id")
            if isinstance(operation_id, str) and operation_id.split(":", 1)[0] not in operation_ids:
                findings.append(
                    ConsistencyFinding(
                        code=ConsistencyFindingCode.UNKNOWN_OPERATION_PROJECTION,
                        resource_type="audit_event",
                        resource_id=entry.entry_hash,
                        related_ids=[str(assertion_id)],
                        detail="scoped audit event references an unknown durable operation",
                    )
                )
            edge_id = entry.payload.get("edge_id")
            if isinstance(edge_id, str) and edge_id not in edge_ids:
                findings.append(
                    ConsistencyFinding(
                        code=ConsistencyFindingCode.AUDIT_REFERENCE_MISSING,
                        resource_type="audit_event",
                        resource_id=entry.entry_hash,
                        related_ids=[str(assertion_id)],
                        detail="scoped audit event references a graph edge that is absent",
                    )
                )
        return findings

    def _valid_source_lineage(self, assertion: DependencySuggestion) -> bool:
        if assertion.source_document_id is None:
            return False
        try:
            document = self._service.document_store.get_document(assertion.source_document_id)
        except Exception:
            return False
        return bool(
            document.version == assertion.source_document_version
            and document.content_sha256 == assertion.source_document_sha256
        )


def _deduplicate(findings: list[ConsistencyFinding]) -> list[ConsistencyFinding]:
    unique: dict[tuple[str, str, tuple[str, ...]], ConsistencyFinding] = {}
    for finding in findings:
        unique.setdefault(finding.key, finding)
    return list(unique.values())


__all__ = ["ConsistencyInspector"]
