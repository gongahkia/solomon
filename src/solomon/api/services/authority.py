# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from solomon.api.service_models import (
    AuthorityChangeRequest,
    DependencyRequest,
    DependencySuggestionDecisionRequest,
    DependencySuggestionRequest,
    ReferenceExtractionRequest,
    StalenessPredictionRequest,
    VerificationRequest,
)
from solomon.api.services.base import ServiceDelegate
from solomon.api.services.common import digest, parse_iso_datetime
from solomon.audit.journal import sign_verification_attestation
from solomon.currency.engine import register_authority_change
from solomon.currency.models import KnowledgeItem
from solomon.currency.prediction import StalenessRiskReport, predict_staleness_risk
from solomon.errors import BadRequestError
from solomon.graph.models import DependencyEdge
from solomon.graph.propagation import CurrencyPropagator
from solomon.graph.suggestions import (
    DependencySuggestion,
    ReferenceExtraction,
    SuggestionDecision,
    confirm_suggestion,
    extract_defined_terms_and_citations,
    reject_suggestion,
    suggest_authority_dependencies,
    suggest_authority_dependencies_with_llm,
)
from solomon.graph.visualization import GraphFormat, dependency_graph_view, render_dependency_graph
from solomon.orchestrator.models import ModelRouter


class AuthorityService(ServiceDelegate):
    def evaluate_currency(self, item_id: str, *, as_of: datetime | None = None) -> dict[str, Any]:
        return self.currency_cache.get_or_evaluate(self._get_item(item_id), as_of=as_of).model_dump(mode="json")

    def record_verification(self, item_id: str, request: VerificationRequest) -> KnowledgeItem:
        item = self._get_item(item_id)
        from solomon.api import service as service_module

        recorded = service_module.record_verification(
            item,
            by=request.by,
            outcome=request.outcome,
            successor_id=request.successor_id,
            recorded_at=request.recorded_at,
        )
        self.store.update_item(recorded.item, event_type="knowledge_item_verified")
        self.currency_cache.invalidate({item_id})
        if self.attestation_key is not None:
            attestation = sign_verification_attestation(
                recorded.item,
                verified_by=request.by,
                outcome=request.outcome.value,
                signing_key=self.attestation_key,
            )
            self.audit.log_verification_attestation(attestation)
        return recorded.item

    def register_authority_change(self, authority_id: str, request: AuthorityChangeRequest) -> dict[str, Any]:
        from datetime import datetime

        impact = register_authority_change(
            authority_id=authority_id,
            new_version=request.new_version,
            changed_at=datetime.fromisoformat(request.changed_at),
            graph=self.graph,
            store=self.store,
        )
        self.currency_cache.invalidate(set(impact.stale_item_ids))
        self.audit.log_impact(impact)
        return impact.model_dump(mode="json")

    def add_dependency(self, request: DependencyRequest) -> DependencyEdge:
        edge = DependencyEdge(
            source_id=request.source_id,
            target_id=request.target_id,
            edge_type=request.edge_type,
            target_kind=request.target_kind,  # type: ignore[arg-type]
            confidence=request.confidence,
            created_by=request.created_by,
            reason=request.reason,
        )
        return self.graph.add_dependency(edge)

    def suggest_dependencies(
        self,
        request: DependencySuggestionRequest,
        *,
        router: ModelRouter | None = None,
    ) -> list[DependencySuggestion]:
        item = self._get_item(request.item_id)
        return self._create_dependency_suggestions(
            item,
            use_llm=request.use_llm,
            router=router,
        )

    def dependency_suggestions(
        self,
        *,
        item_id: str | None = None,
        decision: SuggestionDecision | None = None,
        limit: int = 100,
    ) -> list[DependencySuggestion]:
        return self.graph.list_dependency_suggestions(item_id=item_id, decision=decision, limit=limit)

    def confirm_dependency_suggestion(
        self,
        suggestion_id: str,
        request: DependencySuggestionDecisionRequest,
    ) -> DependencyEdge:
        suggestion = self.graph.get_dependency_suggestion(suggestion_id)
        if suggestion.decision is SuggestionDecision.CONFIRMED:
            return suggestion.suggested_edge
        if suggestion.decision is SuggestionDecision.REJECTED:
            raise BadRequestError("rejected dependency suggestions cannot be confirmed")
        edge = confirm_suggestion(suggestion, by=request.by)
        edge = self.graph.add_dependency(edge)
        confirmed = suggestion.model_copy(
            update={
                "decision": SuggestionDecision.CONFIRMED,
                "decided_by": request.by,
                "decided_at": datetime.now(timezone.utc),
                "suggested_edge": edge,
            }
        )
        self.graph.update_dependency_suggestion(confirmed)
        self.currency_cache.invalidate({edge.source_id})
        self.audit.append(
            "dependency_suggestion_confirmed",
            {
                "suggestion_id": suggestion_id,
                "item_id": edge.source_id,
                "target_id": edge.target_id,
                "edge_id": edge.id,
                "by": request.by,
            },
        )
        return edge

    def reject_dependency_suggestion(
        self,
        suggestion_id: str,
        request: DependencySuggestionDecisionRequest,
    ) -> DependencySuggestion:
        suggestion = self.graph.get_dependency_suggestion(suggestion_id)
        if suggestion.decision is SuggestionDecision.REJECTED:
            return suggestion
        if suggestion.decision is SuggestionDecision.CONFIRMED:
            raise BadRequestError("confirmed dependency suggestions cannot be rejected")
        rejected = reject_suggestion(suggestion, by=request.by)
        self.graph.update_dependency_suggestion(rejected)
        self.audit.append(
            "dependency_suggestion_rejected",
            {
                "suggestion_id": suggestion_id,
                "item_id": rejected.item_id,
                "target_id": rejected.suggested_edge.target_id,
                "by": request.by,
            },
        )
        return rejected

    def impact_query(self, authority_id: str, *, as_of: datetime | None = None) -> dict[str, Any]:
        timestamp = as_of or self._deterministic_store_timestamp()
        return CurrencyPropagator(graph=self.graph, store=self.store).impact_query(
            authority_id,
            as_of=timestamp,
        ).model_dump(mode="json")

    def dependency_graph(
        self,
        *,
        output_format: GraphFormat = "mermaid",
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> str:
        view = dependency_graph_view(graph=self.graph, store=self.store, matter_id=matter_id, client_id=client_id)
        return render_dependency_graph(view, output_format=output_format)

    def extract_references(self, request: ReferenceExtractionRequest) -> ReferenceExtraction:
        return extract_defined_terms_and_citations(content=request.content)

    def predict_staleness(self, request: StalenessPredictionRequest) -> StalenessRiskReport:
        return predict_staleness_risk(
            request.pending_amendments,
            graph=self.graph,
            store=self.store,
            as_of=parse_iso_datetime(request.as_of) if request.as_of else None,
            lookahead_days=request.lookahead_days,
        )

    def _create_dependency_suggestions(
        self,
        item: KnowledgeItem,
        *,
        use_llm: bool = False,
        router: ModelRouter | None = None,
    ) -> list[DependencySuggestion]:
        suggestions = suggest_authority_dependencies(
            item_id=item.id,
            content=item.content,
            boundary=self.boundary,
            matter_id=item.matter_id,
        )
        if use_llm:
            if router is None:
                raise BadRequestError("LLM dependency suggestion requires a model router")
            suggestions.extend(
                suggest_authority_dependencies_with_llm(
                    item_id=item.id,
                    content=item.content,
                    boundary=self.boundary,
                    router=router,
                    matter_id=item.matter_id,
                )
            )
        stored: list[DependencySuggestion] = []
        existing_edges = {
            (edge.target_id, edge.edge_type)
            for edge in self.graph.get_dependencies(item.id)
            if edge.valid_to is None
        }
        existing_suggestions = {
            (suggestion.suggested_edge.target_id, suggestion.suggested_edge.edge_type)
            for suggestion in self.graph.list_dependency_suggestions(item_id=item.id)
        }
        for suggestion in suggestions:
            key = (suggestion.suggested_edge.target_id, suggestion.suggested_edge.edge_type)
            if key in existing_edges or key in existing_suggestions:
                continue
            stored_suggestion = self.graph.add_dependency_suggestion(suggestion)
            existing_suggestions.add(key)
            stored.append(stored_suggestion)
            self.audit.append(
                "dependency_suggestion_created",
                {
                    "suggestion_id": stored_suggestion.id,
                    "item_id": stored_suggestion.item_id,
                    "target_id": stored_suggestion.suggested_edge.target_id,
                    "edge_type": stored_suggestion.suggested_edge.edge_type.value,
                    "source": stored_suggestion.source,
                    "authority_ref_sha256": digest(stored_suggestion.authority_ref),
                },
            )
        return stored
