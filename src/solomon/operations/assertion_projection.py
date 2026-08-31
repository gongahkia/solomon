# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from solomon.audit.journal import AuditAttribution
from solomon.graph.suggestions import DependencySuggestion, SuggestionDecision, confirm_suggestion
from solomon.operations.execution import OperationRequiresIntervention
from solomon.operations.failure_injection import OperationFailureInjector
from solomon.operations.models import OperationPhase, OperationRecord, OperationStatus, OperationType


class AssertionConfirmationProjection:
    """Idempotently project one already-authorized governed confirmation from its journal record."""

    def __init__(
        self,
        *,
        lifecycle: Any,
        operation_store: Any,
        failure_injector: OperationFailureInjector | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._operation_store = operation_store
        self._failure_injector = failure_injector or OperationFailureInjector()

    def apply(self, operation: OperationRecord, worker_id: str) -> OperationRecord:
        if operation.operation_type is not OperationType.ASSERTION_CONFIRM:
            raise OperationRequiresIntervention("operation type is not an assertion confirmation")
        if operation.status is not OperationStatus.CLAIMED:
            raise OperationRequiresIntervention("assertion confirmation is not actively claimed")
        if operation.assertion_id is None:
            raise OperationRequiresIntervention("assertion confirmation has no assertion ID")
        assertion = self._lifecycle.get(
            operation.assertion_id,
            matter_id=operation.scope.matter_id,
            client_id=operation.scope.client_id,
        )
        self._validate(operation, assertion)
        current = operation
        edge = assertion.suggested_edge
        if current.last_successful_checkpoint not in {
            OperationPhase.GRAPH,
            OperationPhase.CURRENCY,
            OperationPhase.AUDIT,
        }:
            self._failure_injector.hit("during_graph_edge_projection")
            # Persist the authorized review decision before exposing its edge. A crash
            # can then leave a confirmed assertion awaiting projection, but never an
            # edge attached to an assertion that remains pending/rejected/deferred.
            edge = confirm_suggestion(assertion, by=operation.actor_id)
            assertion = self._confirm_assertion(assertion, edge)
            edge = self._edge_for(assertion, by=operation.actor_id)
            self._failure_injector.hit("after_graph_edge_before_ack")
            current = self._operation_store.checkpoint(
                current.id,
                worker_id=worker_id,
                phase=OperationPhase.GRAPH,
                result_entity_id=assertion.id,
                result_edge_id=edge.id,
            )

        if current.last_successful_checkpoint not in {OperationPhase.CURRENCY, OperationPhase.AUDIT}:
            assertion = self._lifecycle._get_assertion(assertion.id)
            self._failure_injector.hit("during_currency_propagation")
            self._lifecycle._currency_cache.invalidate({edge.source_id})
            self._lifecycle._on_confirmed_edge(edge)
            current = self._operation_store.checkpoint(
                current.id,
                worker_id=worker_id,
                phase=OperationPhase.CURRENCY,
                result_entity_id=assertion.id,
                result_edge_id=edge.id,
            )

        if current.last_successful_checkpoint is not OperationPhase.AUDIT:
            self._failure_injector.hit("after_currency_before_audit")
            review_entry = self._lifecycle._audit.append_idempotent(
                "dependency_assertion_confirmed",
                {**_assertion_payload(assertion), "edge_id": edge.id},
                operation_id=f"{current.id}:review",
                attribution=AuditAttribution(actor_id=operation.actor_id, correlation_id=operation.correlation_id),
            )
            edge_entry = self._lifecycle._audit.append_idempotent(
                "dependency_assertion_edge_linked",
                {"assertion_id": assertion.id, "edge_id": edge.id},
                operation_id=f"{current.id}:edge",
                attribution=AuditAttribution(actor_id=operation.actor_id, correlation_id=operation.correlation_id),
            )
            audit_updates: dict[str, str] = {}
            if assertion.review_audit_id is None:
                audit_updates["review_audit_id"] = review_entry.entry_hash
            if assertion.edge_audit_id is None:
                audit_updates["edge_audit_id"] = edge_entry.entry_hash
            if audit_updates:
                assertion = assertion.model_copy(update=audit_updates)
                self._lifecycle._graph.update_dependency_suggestion(assertion)
            current = self._operation_store.checkpoint(
                current.id,
                worker_id=worker_id,
                phase=OperationPhase.AUDIT,
                result_entity_id=assertion.id,
                result_edge_id=edge.id,
                audit_entry_hash=edge_entry.entry_hash,
            )
        return cast(
            OperationRecord,
            self._operation_store.complete(
                current.id,
                worker_id=worker_id,
                result_entity_id=assertion.id,
                result_edge_id=edge.id,
            ),
        )

    def _validate(self, operation: OperationRecord, assertion: DependencySuggestion) -> None:
        if assertion.source not in {"human", "trusted_upstream"}:
            raise OperationRequiresIntervention("assertion origin is not governed")
        if assertion.matter_id != operation.scope.matter_id or assertion.client_id != operation.scope.client_id:
            raise OperationRequiresIntervention("assertion scope does not match immutable operation scope")
        if assertion.created_by == operation.actor_id:
            raise OperationRequiresIntervention("creator cannot confirm an assertion during recovery")
        if assertion.decision in {SuggestionDecision.REJECTED, SuggestionDecision.WITHDRAWN}:
            raise OperationRequiresIntervention("terminal negative assertion cannot be confirmed during recovery")
        if assertion.decision is SuggestionDecision.DEFERRED and operation.requested_transition != "confirmed":
            raise OperationRequiresIntervention("deferred assertion transition does not match operation")

    def _edge_for(self, assertion: DependencySuggestion, *, by: str) -> Any:
        edge = confirm_suggestion(assertion, by=by)
        try:
            return self._lifecycle._graph.add_dependency(edge)
        except Exception as exc:
            try:
                persisted = self._lifecycle._graph.get_edge(edge.id)
            except KeyError:
                raise exc from None
            if persisted.source_suggestion_id != assertion.id:
                raise OperationRequiresIntervention("existing edge does not carry assertion provenance") from exc
            return persisted

    def _confirm_assertion(self, assertion: DependencySuggestion, edge: Any) -> DependencySuggestion:
        latest = self._lifecycle._get_assertion(assertion.id)
        if latest.decision is SuggestionDecision.CONFIRMED:
            if latest.suggested_edge.id != edge.id:
                raise OperationRequiresIntervention("confirmed assertion points to a different edge")
            return cast(DependencySuggestion, latest)
        if latest.decision in {SuggestionDecision.REJECTED, SuggestionDecision.WITHDRAWN}:
            raise OperationRequiresIntervention("assertion became terminal before projection")
        confirmed = latest.model_copy(
            update={
                "decision": SuggestionDecision.CONFIRMED,
                "decided_by": edge.created_by,
                "decided_at": datetime.now(timezone.utc),
                "decision_reason": "durably projected confirmation",
                "suggested_edge": edge,
                "state_version": latest.state_version + 1,
            }
        )
        self._lifecycle._graph.update_dependency_suggestion(confirmed)
        return cast(DependencySuggestion, confirmed)


def _assertion_payload(assertion: DependencySuggestion) -> dict[str, Any]:
    from solomon.api.services.dependency_assertions import _assertion_audit_payload

    return _assertion_audit_payload(assertion)


__all__ = ["AssertionConfirmationProjection"]
