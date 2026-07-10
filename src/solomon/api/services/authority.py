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
    VerificationAssignmentRequest,
    VerificationRequest,
    VerificationReviewRequest,
)
from solomon.api.services.base import ServiceDelegate
from solomon.api.services.common import digest, parse_iso_datetime
from solomon.audit.journal import sign_verification_attestation
from solomon.currency.engine import register_authority_change
from solomon.currency.models import CurrencyState, KnowledgeItem, VerifiedState
from solomon.currency.prediction import StalenessRiskReport, predict_staleness_risk
from solomon.currency.verification import (
    VerificationLifecycleEvent,
    VerificationLifecycleState,
    append_verification_event,
    latest_verification_event,
    lifecycle_state_for_outcome,
    verification_history,
)
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
        if not request.basis and not request.source_ref:
            raise BadRequestError("verification basis or source_ref is required")
        item = self._get_item(item_id)
        from solomon.api import service as service_module

        if latest_verification_event(item) is None:
            item = self._append_lifecycle_event(
                item,
                VerificationLifecycleEvent(
                    item_id=item_id,
                    state=VerificationLifecycleState.IN_REVIEW,
                    actor_id=request.by,
                    reviewer_id=request.by,
                    occurred_at=request.recorded_at or datetime.now(timezone.utc),
                    basis="implicit review started by completion",
                    policy_version=self.verification_policy_version,
                    credence_policy_version=self.credence_policy_version,
                    policy_snapshot=self._policy_snapshot(),
                ),
                event_type="verification_lifecycle_in_review",
            )
        recorded = service_module.record_verification(
            item,
            by=request.by,
            outcome=request.outcome,
            successor_id=request.successor_id,
            recorded_at=request.recorded_at,
        )
        event = VerificationLifecycleEvent(
            item_id=item_id,
            state=lifecycle_state_for_outcome(request.outcome.value),
            actor_id=request.by,
            reviewer_id=request.by,
            occurred_at=recorded.recorded_at,
            basis=request.basis,
            source_ref=request.source_ref,
            policy_version=self.verification_policy_version,
            credence_policy_version=self.credence_policy_version,
            policy_snapshot=self._policy_snapshot(),
        )
        updated = append_verification_event(recorded.item, event)
        self.store.update_item(updated, event_type="verification_lifecycle_completed", occurred_at=recorded.recorded_at)
        self.index.upsert_item(updated)
        self.audit.log_verification_lifecycle(event)
        self.currency_cache.invalidate({item_id})
        if self.attestation_key is not None:
            attestation = sign_verification_attestation(
                updated,
                verified_by=request.by,
                outcome=request.outcome.value,
                signing_key=self.attestation_key,
            )
            self.audit.log_verification_attestation(attestation)
        return updated

    def assign_verification(self, item_id: str, request: VerificationAssignmentRequest) -> KnowledgeItem:
        item = self._get_item(item_id)
        timestamp = request.assigned_at or datetime.now(timezone.utc)
        event = VerificationLifecycleEvent(
            item_id=item_id,
            state=VerificationLifecycleState.ASSIGNED,
            actor_id=request.assigned_by,
            reviewer_id=request.reviewer_id,
            role=request.role,
            occurred_at=timestamp,
            basis=request.basis,
            source_ref=request.source_ref,
            policy_version=self.verification_policy_version,
            credence_policy_version=self.credence_policy_version,
            policy_snapshot=self._policy_snapshot(),
        )
        updated = append_verification_event(
            item.model_copy(update={"verified_state": VerifiedState.NEEDS_REVIEW}),
            event,
        )
        return self._write_lifecycle_update(updated, event, event_type="verification_lifecycle_assigned")

    def start_verification_review(self, item_id: str, request: VerificationReviewRequest) -> KnowledgeItem:
        item = self._get_item(item_id)
        timestamp = request.started_at or datetime.now(timezone.utc)
        event = VerificationLifecycleEvent(
            item_id=item_id,
            state=VerificationLifecycleState.IN_REVIEW,
            actor_id=request.reviewer_id,
            reviewer_id=request.reviewer_id,
            occurred_at=timestamp,
            basis=request.basis,
            source_ref=request.source_ref,
            policy_version=self.verification_policy_version,
            credence_policy_version=self.credence_policy_version,
            policy_snapshot=self._policy_snapshot(),
        )
        updated = append_verification_event(item, event)
        return self._write_lifecycle_update(updated, event, event_type="verification_lifecycle_in_review")

    def verification_queue(
        self,
        *,
        reviewer_id: str | None = None,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in self.store.get_many(matter_id=matter_id, client_id=client_id):
            currency = self.evaluate_currency(item.id)
            history = verification_history(item)
            latest = history[-1] if history else None
            assigned_reviewer = item.metadata.get("verification_reviewer_id")
            if reviewer_id is not None and assigned_reviewer != reviewer_id:
                continue
            needs_review = (
                str(currency.get("currency_state")) == CurrencyState.STALE_PENDING_REVERIFICATION.value
                or item.verified_state is VerifiedState.NEEDS_REVIEW
                or bool(item.metadata.get("staleness_reasons"))
            )
            if not needs_review:
                continue
            rows.append(
                {
                    "item": item.model_dump(mode="json"),
                    "currency": currency,
                    "reviewer_id": assigned_reviewer,
                    "verification_status": item.metadata.get("verification_status"),
                    "latest_event": latest.model_dump(mode="json") if latest else None,
                    "history": [event.model_dump(mode="json") for event in history],
                }
            )
        return sorted(rows, key=lambda row: (str(row.get("reviewer_id") or ""), str(row["item"]["id"])))

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
        for stale_item_id in impact.stale_item_ids:
            item = self._get_item(stale_item_id)
            event = latest_verification_event(item)
            if event is not None and event.state is VerificationLifecycleState.REQUESTED:
                self.audit.log_verification_lifecycle(event)
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

    def _append_lifecycle_event(
        self,
        item: KnowledgeItem,
        event: VerificationLifecycleEvent,
        *,
        event_type: str,
    ) -> KnowledgeItem:
        updated = append_verification_event(item, event)
        return self._write_lifecycle_update(updated, event, event_type=event_type)

    def _write_lifecycle_update(
        self,
        item: KnowledgeItem,
        event: VerificationLifecycleEvent,
        *,
        event_type: str,
    ) -> KnowledgeItem:
        self.store.update_item(item, event_type=event_type, occurred_at=event.occurred_at)
        self.index.upsert_item(item)
        self.currency_cache.invalidate({item.id})
        self.audit.log_verification_lifecycle(event)
        return item

    def _policy_snapshot(self) -> dict[str, Any]:
        return {
            "verification_policy": self.currency_cache.policy.model_dump(mode="json"),
            "verification_policy_version": self.verification_policy_version,
            "credence_policy": self.credence.policy.model_dump(mode="json"),
            "credence_policy_version": self.credence_policy_version,
        }
