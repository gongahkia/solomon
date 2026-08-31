# SPDX-License-Identifier: Apache-2.0

"""Service-layer lifecycle for human-reviewed dependency suggestions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from solomon.api.service_models import DependencySuggestionDecisionRequest
from solomon.audit.journal import AuditAttribution, AuditJournal
from solomon.currency.cache import CurrencyEvaluationCache
from solomon.currency.models import KnowledgeItem
from solomon.errors import BadRequestError, NotFoundError
from solomon.graph.models import DependencyEdge
from solomon.graph.suggestions import (
    DependencySuggestion,
    SuggestionDecision,
    confirm_suggestion,
    defer_suggestion,
    reject_suggestion,
)
from solomon.graph.types import DependencyGraphProtocol


class DependencySuggestionLifecycle:
    """Keep suggestion decisions inside the existing graph, audit, and scope controls."""

    def __init__(
        self,
        *,
        graph: DependencyGraphProtocol,
        audit: AuditJournal,
        currency_cache: CurrencyEvaluationCache,
        get_item: Callable[[str], KnowledgeItem],
        on_confirmed_edge: Callable[[DependencyEdge], None],
    ) -> None:
        self._graph = graph
        self._audit = audit
        self._currency_cache = currency_cache
        self._get_item = get_item
        self._on_confirmed_edge = on_confirmed_edge

    def list(
        self,
        *,
        item_id: str | None = None,
        decision: SuggestionDecision | None = None,
        limit: int = 100,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> list[DependencySuggestion]:
        suggestions = self._graph.list_dependency_suggestions(item_id=item_id, decision=decision, limit=limit)
        if matter_id is None and client_id is None:
            return suggestions
        return [
            suggestion
            for suggestion in suggestions
            if self._in_scope(suggestion, matter_id=matter_id, client_id=client_id)
        ]

    def confirm(
        self,
        suggestion_id: str,
        request: DependencySuggestionDecisionRequest,
    ) -> DependencyEdge:
        suggestion = self._get_scoped_suggestion(suggestion_id, request)
        if suggestion.decision is SuggestionDecision.CONFIRMED:
            return suggestion.suggested_edge
        if suggestion.decision is SuggestionDecision.REJECTED:
            raise BadRequestError("rejected dependency suggestions cannot be confirmed")
        edge = self._graph.add_dependency(confirm_suggestion(suggestion, by=request.by))
        self._on_confirmed_edge(edge)
        confirmed = suggestion.model_copy(
            update={
                "decision": SuggestionDecision.CONFIRMED,
                "decided_by": request.by,
                "decided_at": datetime.now(timezone.utc),
                "decision_reason": request.reason,
                "suggested_edge": edge,
            }
        )
        self._graph.update_dependency_suggestion(confirmed)
        self._currency_cache.invalidate({edge.source_id})
        self._audit_decision("confirmed", confirmed, edge_id=edge.id)
        return edge

    def reject(
        self,
        suggestion_id: str,
        request: DependencySuggestionDecisionRequest,
    ) -> DependencySuggestion:
        suggestion = self._get_scoped_suggestion(suggestion_id, request)
        if suggestion.decision is SuggestionDecision.REJECTED:
            return suggestion
        if suggestion.decision is SuggestionDecision.CONFIRMED:
            raise BadRequestError("confirmed dependency suggestions cannot be rejected")
        rejected = reject_suggestion(suggestion, by=request.by).model_copy(update={"decision_reason": request.reason})
        self._graph.update_dependency_suggestion(rejected)
        self._audit_decision("rejected", rejected)
        return rejected

    def defer(
        self,
        suggestion_id: str,
        request: DependencySuggestionDecisionRequest,
    ) -> DependencySuggestion:
        suggestion = self._get_scoped_suggestion(suggestion_id, request)
        if suggestion.decision is SuggestionDecision.DEFERRED:
            return suggestion
        if suggestion.decision is SuggestionDecision.CONFIRMED:
            raise BadRequestError("confirmed dependency suggestions cannot be deferred")
        if suggestion.decision is SuggestionDecision.REJECTED:
            raise BadRequestError("rejected dependency suggestions cannot be deferred")
        if request.reason is None:
            raise BadRequestError("a reason is required when deferring a dependency suggestion")
        deferred = defer_suggestion(suggestion, by=request.by, reason=request.reason)
        self._graph.update_dependency_suggestion(deferred)
        self._audit_decision("deferred", deferred)
        return deferred

    def _get_scoped_suggestion(
        self,
        suggestion_id: str,
        request: DependencySuggestionDecisionRequest,
    ) -> DependencySuggestion:
        suggestion = self._graph.get_dependency_suggestion(suggestion_id)
        if (request.matter_id is not None or request.client_id is not None) and not self._in_scope(
            suggestion,
            matter_id=request.matter_id,
            client_id=request.client_id,
        ):
            raise BadRequestError("dependency suggestion is outside the requested matter or client scope")
        return suggestion

    def _in_scope(
        self,
        suggestion: DependencySuggestion,
        *,
        matter_id: str | None,
        client_id: str | None,
    ) -> bool:
        try:
            item = self._get_item(suggestion.item_id)
        except NotFoundError:
            return False
        return (matter_id is None or item.matter_id == matter_id) and (client_id is None or item.client_id == client_id)

    def _audit_decision(self, decision: str, suggestion: DependencySuggestion, *, edge_id: str | None = None) -> None:
        payload = {
            "suggestion_id": suggestion.id,
            "item_id": suggestion.item_id,
            "target_id": suggestion.suggested_edge.target_id,
            "by": suggestion.decided_by,
        }
        if edge_id is not None:
            payload["edge_id"] = edge_id
        self._audit.append(
            f"dependency_suggestion_{decision}",
            payload,
            attribution=AuditAttribution(
                actor_id=suggestion.decided_by,
                correlation_id=suggestion.audit_correlation_id,
            ),
        )


def source_document_value(item: KnowledgeItem, key: str) -> str | None:
    source_document = item.metadata.get("source_document")
    value = source_document.get(key) if isinstance(source_document, dict) else None
    return value if isinstance(value, str) else None


def source_document_version(item: KnowledgeItem) -> int | None:
    source_document = item.metadata.get("source_document")
    value = source_document.get("version") if isinstance(source_document, dict) else None
    return value if isinstance(value, int) else None


def source_document_offset(item: KnowledgeItem) -> int:
    source_document = item.metadata.get("source_document")
    value = source_document.get("span_start") if isinstance(source_document, dict) else None
    return value if isinstance(value, int) else 0
