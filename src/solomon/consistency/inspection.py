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
        suggestions = self._suggestions(item_ids, assertion_ids={assertion.id for assertion in assertions})
        source_documents = self._source_documents(assertions)
        edges = self._service.graph.subgraph_for_scope(
            store=self._service.store,
            matter_id=scope.matter_id,
            client_id=scope.client_id,
        )
        operations = self._operations(
            scope,
            item_ids=item_ids,
            assertions=assertions,
            source_documents=source_documents,
        )
        audit_entries = self._audit_entries(
            item_ids=item_ids,
            assertions=assertions,
            suggestions=suggestions,
            edges=edges,
            source_documents=source_documents,
            operations=operations,
        )
        findings: list[ConsistencyFinding] = []
        findings.extend(self._assertion_findings(assertions, edges))
        findings.extend(self._edge_findings(assertions, suggestions, edges, item_ids))
        findings.extend(self._source_findings(assertions, operations))
        findings.extend(self._operation_findings(assertions, suggestions, edges, operations, timestamp, stuck_after))
        findings.extend(self._currency_findings(scope, items, operations))
        findings.extend(self._audit_findings(assertions, edges, operations, audit_entries))
        return ConsistencyReport.create(
            scope=scope,
            findings=_deduplicate(findings),
            observed_state={
                "items": [item.model_dump(mode="json") for item in items],
                "assertions": [assertion.model_dump(mode="json") for assertion in assertions],
                "suggestions": [suggestion.model_dump(mode="json") for suggestion in suggestions],
                "edges": [edge.model_dump(mode="json") for edge in edges],
                "operations": [operation.model_dump(mode="json") for operation in operations],
                "source_documents": [document.model_dump(mode="json") for document in source_documents],
                "audit_entries": [entry.model_dump(mode="json") for entry in audit_entries],
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

    def _suggestions(self, item_ids: set[str], *, assertion_ids: set[str]) -> list[DependencySuggestion]:
        """Return non-governed suggestions whose source item is already exactly scope-filtered."""

        suggestions: list[DependencySuggestion] = []
        for item_id in sorted(item_ids):
            suggestions.extend(self._service.graph.list_dependency_suggestions(item_id=item_id, limit=10_000))
        return [suggestion for suggestion in suggestions if suggestion.id not in assertion_ids]

    def _source_documents(self, assertions: list[DependencySuggestion]) -> list[Any]:
        documents: dict[str, Any] = {}
        for assertion in assertions:
            if assertion.source_document_id is None:
                continue
            document = self._source_document_or_none(assertion.source_document_id)
            if document is None:
                continue
            documents[document.id] = document
            for candidate in self._service.document_store.list_documents(document.source_id):
                if candidate.previous_version_id == document.id:
                    documents[candidate.id] = candidate
        return [documents[document_id] for document_id in sorted(documents)]

    def _operations(
        self,
        scope: ConsistencyScope,
        *,
        item_ids: set[str],
        assertions: list[DependencySuggestion],
        source_documents: list[Any],
    ) -> list[OperationRecord]:
        assertion_ids = {assertion.id for assertion in assertions}
        document_ids = {document.id for document in source_documents}
        relevant: list[OperationRecord] = []
        for operation in self._service.operation_store.list(limit=10_000):
            if operation.scope.tenant_id != scope.tenant_id:
                continue
            if operation.scope == OperationScope(
                tenant_id=scope.tenant_id,
                matter_id=scope.matter_id,
                client_id=scope.client_id,
            ):
                relevant.append(operation)
                continue
            if (
                operation.operation_type is OperationType.EVIDENCE_INGESTION
                and operation.target_resource_id in document_ids
            ):
                relevant.append(operation)
                continue
            if (
                operation.operation_type is OperationType.SUGGESTION_GENERATION
                and operation.target_resource_id in item_ids
            ):
                relevant.append(operation)
                continue
            if (
                operation.operation_type is OperationType.AUTHORITY_CHANGE_PROPAGATION
                and operation.target_resource_id is not None
                and self._authority_change_affects_items(operation, item_ids)
            ):
                relevant.append(operation)
                continue
            if operation.assertion_id in assertion_ids:
                relevant.append(operation)
        return relevant

    def _source_document_or_none(self, document_id: str) -> Any | None:
        try:
            return self._service.document_store.get_document(document_id)
        except Exception:
            return None

    def _authority_change_affects_items(self, operation: OperationRecord, item_ids: set[str]) -> bool:
        if operation.target_resource_id is None:
            return False
        impact = CurrencyPropagator(graph=self._service.graph, store=self._service.store).impact_query(
            operation.target_resource_id
        )
        return bool(item_ids.intersection(impact.stale_item_ids))

    def _audit_entries(
        self,
        *,
        item_ids: set[str],
        assertions: list[DependencySuggestion],
        suggestions: list[DependencySuggestion],
        edges: list[Any],
        source_documents: list[Any],
        operations: list[OperationRecord],
    ) -> list[Any]:
        assertion_ids = {assertion.id for assertion in assertions}
        suggestion_ids = {suggestion.id for suggestion in suggestions}
        edge_ids = {edge.id for edge in edges}
        document_ids = {document.id for document in source_documents}
        operation_ids = {operation.id for operation in operations}
        audit_hashes = {
            audit_hash
            for assertion in assertions
            for audit_hash in (
                assertion.creation_audit_id,
                assertion.review_audit_id,
                assertion.edge_audit_id,
                assertion.reverification_audit_id,
            )
            if audit_hash is not None
        }
        audit_hashes.update(audit_hash for operation in operations for audit_hash in operation.audit_entry_hashes)
        selected: list[Any] = []
        for entry in self._service.audit.list_entries():
            payload = entry.payload
            operation_id = payload.get("operation_id")
            operation_base = operation_id.split(":", 1)[0] if isinstance(operation_id, str) else None
            if (
                entry.entry_hash in audit_hashes
                or payload.get("assertion_id") in assertion_ids
                or payload.get("suggestion_id") in suggestion_ids
                or payload.get("item_id") in item_ids
                or payload.get("edge_id") in edge_ids
                or payload.get("document_id") in document_ids
                or operation_base in operation_ids
            ):
                selected.append(entry)
        return selected

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
        suggestions: list[DependencySuggestion],
        edges: list[Any],
        item_ids: set[str],
    ) -> list[ConsistencyFinding]:
        indexed = {origin.id: origin for origin in [*assertions, *suggestions]}
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
                        detail="graph edge has no originating reviewed provenance",
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
                        detail="graph edge does not match a valid confirmed reviewed origin",
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
        suggestions: list[DependencySuggestion],
        edges: list[Any],
        operations: list[OperationRecord],
        now: datetime,
        stuck_after: timedelta,
    ) -> list[ConsistencyFinding]:
        findings: list[ConsistencyFinding] = []
        assertion_by_id = {assertion.id: assertion for assertion in assertions}
        suggestion_by_id = {suggestion.id: suggestion for suggestion in suggestions}
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
            if operation.operation_type is OperationType.ASSERTION_CREATE and (
                assertion is None or assertion.creation_audit_id is None
            ):
                findings.append(
                    ConsistencyFinding(
                        code=ConsistencyFindingCode.COMPLETED_PROJECTION_MISSING,
                        resource_type="knowledge_operation",
                        resource_id=operation.id,
                        related_ids=[operation.assertion_id] if operation.assertion_id else [],
                        detail="completed assertion creation has no linked audit provenance",
                    )
                )
            if operation.operation_type is OperationType.SUGGESTION_CONFIRM:
                suggestion = suggestion_by_id.get(operation.suggestion_id or "")
                if suggestion is None or suggestion.decision is not SuggestionDecision.CONFIRMED or (
                    suggestion.suggested_edge.id not in edge_ids
                ):
                    findings.append(
                        ConsistencyFinding(
                            code=ConsistencyFindingCode.COMPLETED_PROJECTION_MISSING,
                            resource_type="dependency_suggestion",
                            resource_id=operation.suggestion_id or operation.id,
                            related_ids=[operation.id],
                            detail="completed suggestion confirmation has no expected graph projection",
                        )
                    )
            if operation.operation_type is OperationType.CANDIDATE_PROMOTION:
                candidate = None
                if operation.source_resource_id is not None:
                    try:
                        candidate = self._service.document_store.get_candidate(operation.source_resource_id)
                    except Exception:
                        candidate = None
                if candidate is None or candidate.promotion_item_id != operation.target_resource_id:
                    findings.append(
                        ConsistencyFinding(
                            code=ConsistencyFindingCode.COMPLETED_PROJECTION_MISSING,
                            resource_type="candidate_claim",
                            resource_id=operation.source_resource_id or operation.id,
                            related_ids=[operation.id],
                            detail="completed candidate promotion has no expected SQLite source marker",
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

    def _currency_findings(
        self,
        scope: ConsistencyScope,
        items: list[Any],
        operations: list[OperationRecord],
    ) -> list[ConsistencyFinding]:
        item_ids = {item.id for item in items}
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
        entries: list[Any],
    ) -> list[ConsistencyFinding]:
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
