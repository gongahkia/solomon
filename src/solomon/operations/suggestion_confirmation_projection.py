# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from solomon.audit.journal import AuditAttribution
from solomon.graph.suggestions import DependencySuggestion, SuggestionDecision, confirm_suggestion
from solomon.operations.execution import OperationRequiresIntervention
from solomon.operations.failure_injection import OperationFailureInjector
from solomon.operations.models import OperationPhase, OperationRecord, OperationStatus, OperationType


class SuggestionConfirmationProjection:
    """Idempotently project a human-reviewed, non-governed suggestion confirmation."""

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
        if operation.operation_type is not OperationType.SUGGESTION_CONFIRM:
            raise OperationRequiresIntervention("operation type is not a suggestion confirmation")
        if operation.status is not OperationStatus.CLAIMED or operation.suggestion_id is None:
            raise OperationRequiresIntervention("suggestion confirmation is incomplete or not claimed")
        suggestion = self._lifecycle._graph.get_dependency_suggestion(operation.suggestion_id)
        item = self._lifecycle._get_item(suggestion.item_id)
        if item.matter_id != operation.scope.matter_id or item.client_id != operation.scope.client_id:
            raise OperationRequiresIntervention("suggestion scope does not match immutable operation scope")
        current = operation
        edge = suggestion.suggested_edge
        if current.last_successful_checkpoint not in {
            OperationPhase.GRAPH,
            OperationPhase.CURRENCY,
            OperationPhase.AUDIT,
        }:
            self._failure_injector.hit("during_graph_edge_projection")
            edge = confirm_suggestion(suggestion, by=operation.actor_id)
            suggestion = self._confirm_suggestion(operation, suggestion, edge)
            edge = self._edge_for(suggestion, by=operation.actor_id)
            self._failure_injector.hit("after_graph_edge_before_ack")
            current = self._operation_store.checkpoint(
                current.id,
                worker_id=worker_id,
                phase=OperationPhase.GRAPH,
                result_entity_id=suggestion.id,
                result_edge_id=edge.id,
            )
        if current.last_successful_checkpoint not in {OperationPhase.CURRENCY, OperationPhase.AUDIT}:
            self._failure_injector.hit("during_currency_propagation")
            self._lifecycle._currency_cache.invalidate({edge.source_id})
            self._lifecycle._on_confirmed_edge(edge)
            current = self._operation_store.checkpoint(
                current.id,
                worker_id=worker_id,
                phase=OperationPhase.CURRENCY,
                result_entity_id=suggestion.id,
                result_edge_id=edge.id,
            )
        if current.last_successful_checkpoint is not OperationPhase.AUDIT:
            self._failure_injector.hit("after_currency_before_audit")
            entry = self._lifecycle._audit.append_idempotent(
                "dependency_suggestion_confirmed",
                {
                    "suggestion_id": suggestion.id,
                    "item_id": suggestion.item_id,
                    "target_id": edge.target_id,
                    "by": operation.actor_id,
                    "edge_id": edge.id,
                },
                operation_id=f"{current.id}:audit",
                attribution=AuditAttribution(actor_id=operation.actor_id, correlation_id=operation.correlation_id),
            )
            current = self._operation_store.checkpoint(
                current.id,
                worker_id=worker_id,
                phase=OperationPhase.AUDIT,
                result_entity_id=suggestion.id,
                result_edge_id=edge.id,
                audit_entry_hash=entry.entry_hash,
            )
        return cast(
            OperationRecord,
            self._operation_store.complete(
                current.id,
                worker_id=worker_id,
                result_entity_id=suggestion.id,
                result_edge_id=edge.id,
            ),
        )

    def _confirm_suggestion(
        self,
        operation: OperationRecord,
        suggestion: DependencySuggestion,
        edge: Any,
    ) -> DependencySuggestion:
        latest = self._lifecycle._graph.get_dependency_suggestion(suggestion.id)
        if latest.decision is SuggestionDecision.CONFIRMED:
            if latest.suggested_edge.id != edge.id:
                raise OperationRequiresIntervention("confirmed suggestion points to a different edge")
            return cast(DependencySuggestion, latest)
        if latest.decision in {SuggestionDecision.REJECTED, SuggestionDecision.WITHDRAWN}:
            raise OperationRequiresIntervention("suggestion became terminal before projection")
        expected_state_version = operation.payload.get("expected_state_version")
        if not isinstance(expected_state_version, int) or latest.state_version != expected_state_version:
            raise OperationRequiresIntervention("suggestion state no longer matches the authorized confirmation")
        confirmed = latest.model_copy(
            update={
                "decision": SuggestionDecision.CONFIRMED,
                "decided_by": operation.actor_id,
                "decided_at": datetime.now(timezone.utc),
                "decision_reason": "durably projected confirmation",
                "suggested_edge": edge,
                "state_version": latest.state_version + 1,
            }
        )
        self._lifecycle._graph.update_dependency_suggestion(confirmed)
        return cast(DependencySuggestion, confirmed)

    def _edge_for(self, suggestion: DependencySuggestion, *, by: str) -> Any:
        edge = confirm_suggestion(suggestion, by=by)
        try:
            return self._lifecycle._graph.add_dependency(edge)
        except Exception as exc:
            try:
                persisted = self._lifecycle._graph.get_edge(edge.id)
            except KeyError:
                raise exc from None
            if persisted.source_suggestion_id != suggestion.id:
                raise OperationRequiresIntervention("existing edge does not carry suggestion provenance") from exc
            return persisted


__all__ = ["SuggestionConfirmationProjection"]
