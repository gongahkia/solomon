# SPDX-License-Identifier: Apache-2.0

"""Governed, human-reviewed dependency assertions on the existing suggestion lifecycle."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from solomon.api.service_models import (
    DependencyAssertionCreateRequest,
    DependencyAssertionDecisionRequest,
    DependencyAssertionWithdrawRequest,
)
from solomon.audit.journal import AuditAttribution, AuditJournal
from solomon.authority_identifiers import SQLiteAuthorityIdentifierStore
from solomon.authority_sources import SQLiteAuthoritySourceRegistry
from solomon.currency.cache import CurrencyEvaluationCache
from solomon.currency.models import KnowledgeItem
from solomon.errors import BadRequestError, ConflictError, NotFoundError, PolicyRefusalError
from solomon.graph.models import DependencyEdge, EdgeConfidence, EdgeType
from solomon.graph.suggestions import (
    AssertionEvidenceKind,
    DependencySuggestion,
    SuggestionDecision,
)
from solomon.graph.types import DependencyGraphProtocol
from solomon.sources.models import SourceDocument
from solomon.sources.store import SourceDocumentNotFoundError, SourceNotFoundError, SQLiteDocumentStore


class GovernedDependencyAssertionLifecycle:
    """Create and decide explicit assertions without creating a second graph workflow."""

    def __init__(
        self,
        *,
        graph: DependencyGraphProtocol,
        audit: AuditJournal,
        currency_cache: CurrencyEvaluationCache,
        get_item: Callable[[str], KnowledgeItem],
        document_store: SQLiteDocumentStore,
        authority_sources: SQLiteAuthoritySourceRegistry,
        authority_identifiers: SQLiteAuthorityIdentifierStore,
        on_confirmed_edge: Callable[[DependencyEdge], None],
        schedule_creation: Callable[[DependencySuggestion], DependencySuggestion],
        schedule_confirmation: Callable[[DependencySuggestion, DependencyAssertionDecisionRequest], DependencyEdge],
        schedule_transition: Callable[[DependencySuggestion], DependencySuggestion],
    ) -> None:
        self._graph = graph
        self._audit = audit
        self._currency_cache = currency_cache
        self._get_item = get_item
        self._document_store = document_store
        self._authority_sources = authority_sources
        self._authority_identifiers = authority_identifiers
        self._on_confirmed_edge = on_confirmed_edge
        self._schedule_creation = schedule_creation
        self._schedule_confirmation = schedule_confirmation
        self._schedule_transition = schedule_transition

    def create(self, request: DependencyAssertionCreateRequest) -> DependencySuggestion:
        source_item = self._get_item(request.item_id)
        document = self._source_document_for(source_item, request)
        target_id, edge_type = self._resolve_target(source_item, request)
        request_sha256 = _request_sha256(request)
        existing = self._by_idempotency(request.origin, request.idempotency_key)
        if existing is not None:
            if existing.request_sha256 != request_sha256:
                raise ConflictError("idempotency key was already used for a different dependency assertion")
            return existing if existing.creation_audit_id is not None else self._schedule_creation(existing)
        self._require_traced_successor(
            request,
            source_item=source_item,
            target_id=target_id,
            evidence_raw=evidence_raw_for(request),
        )

        evidence_raw = evidence_raw_for(request)
        assertion = DependencySuggestion(
            item_id=source_item.id,
            authority_ref=target_id,
            suggested_edge=DependencyEdge(
                source_id=source_item.id,
                target_id=target_id,
                edge_type=edge_type,
                target_kind=request.target_kind,
                confidence=EdgeConfidence.HUMAN_ASSERTED,
                created_by=request.created_by,
                reason=f"governed {request.assertion_type.value} assertion pending review",
            ),
            source=request.origin,
            source_document_id=document.id,
            source_document_version=document.version,
            source_document_sha256=document.content_sha256,
            source_resource_id=document.source_id,
            source_span_start=request.quote_start,
            source_span_end=request.quote_end,
            source_span=request.quote,
            matter_id=source_item.matter_id,
            client_id=source_item.client_id,
            explanation="explicit governed dependency assertion; human review required",
            audit_correlation_id=request.correlation_id
            or f"dependency_assertion:{source_item.id}:{request.idempotency_key}",
            assertion_type=request.assertion_type,
            evidence_kind=request.evidence_kind,
            evidence_raw=evidence_raw,
            rationale=request.rationale,
            created_by=request.created_by,
            idempotency_key=request.idempotency_key,
            request_sha256=request_sha256,
            trusted_upstream_ref=request.trusted_upstream_ref,
            revision_of=request.revision_of,
        )
        try:
            persisted = self._graph.add_dependency_suggestion(assertion)
        except Exception as exc:
            existing = self._by_idempotency(request.origin, request.idempotency_key)
            if existing is None:
                raise exc
            if existing.request_sha256 != request_sha256:
                raise ConflictError("idempotency key was already used for a different dependency assertion") from exc
            return existing
        return self._schedule_creation(persisted)

    def list_assertions(
        self,
        *,
        item_id: str | None = None,
        origin: str | None = None,
        state: SuggestionDecision | None = None,
        target_id: str | None = None,
        creator: str | None = None,
        needs_reverification: bool | None = None,
        matter_id: str | None = None,
        client_id: str | None = None,
        limit: int = 100,
    ) -> list[DependencySuggestion]:
        sources = (origin,) if origin is not None else ("human", "trusted_upstream")
        assertions: list[DependencySuggestion] = []
        for source in sources:
            assertions.extend(
                self._graph.list_dependency_suggestions(
                    item_id=item_id,
                    decision=state,
                    source=source,
                    target_id=target_id,
                    created_by=creator,
                    needs_reverification=needs_reverification,
                    limit=limit,
                )
            )
        scoped = [
            assertion for assertion in assertions if self._in_scope(assertion, matter_id=matter_id, client_id=client_id)
        ]
        return sorted(scoped, key=lambda assertion: (assertion.created_at, assertion.id))[:limit]

    def get(
        self,
        assertion_id: str,
        *,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> DependencySuggestion:
        assertion = self._get_assertion(assertion_id)
        self._require_scope(assertion, matter_id=matter_id, client_id=client_id)
        return assertion

    def decide(
        self, assertion_id: str, request: DependencyAssertionDecisionRequest
    ) -> DependencySuggestion | DependencyEdge:
        assertion = self.get(assertion_id, matter_id=request.matter_id, client_id=request.client_id)
        self._check_version(assertion, request.expected_state_version)
        self._require_separation_of_duties(assertion, reviewer=request.by)
        if request.decision == "confirmed":
            if assertion.decision in {SuggestionDecision.REJECTED, SuggestionDecision.WITHDRAWN}:
                raise BadRequestError("rejected or withdrawn dependency assertions cannot be confirmed")
            return self._schedule_confirmation(assertion, request)
        if request.decision == "rejected":
            return self._transition(assertion, SuggestionDecision.REJECTED, by=request.by, reason=request.reason)
        return self._transition(assertion, SuggestionDecision.DEFERRED, by=request.by, reason=request.reason)

    def withdraw(self, assertion_id: str, request: DependencyAssertionWithdrawRequest) -> DependencySuggestion:
        assertion = self.get(assertion_id, matter_id=request.matter_id, client_id=request.client_id)
        self._check_version(assertion, request.expected_state_version)
        if assertion.decision is SuggestionDecision.CONFIRMED:
            raise BadRequestError("confirmed dependency assertions cannot be withdrawn; create a traced revision")
        if assertion.decision is SuggestionDecision.WITHDRAWN:
            return assertion
        return self._transition(assertion, SuggestionDecision.WITHDRAWN, by=request.by, reason=request.reason)

    def history(
        self,
        assertion_id: str,
        *,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        assertion = self.get(assertion_id, matter_id=matter_id, client_id=client_id)
        audit_entries = [
            entry.model_dump(mode="json")
            for entry in self._audit.list_entries(correlation_id=assertion.audit_correlation_id)
        ]
        return {
            "assertion": assertion.model_dump(mode="json"),
            "edge": assertion.suggested_edge.model_dump(mode="json")
            if assertion.decision is SuggestionDecision.CONFIRMED
            else None,
            "events": self._graph.list_dependency_suggestion_events(assertion_id),
            "audit_entries": audit_entries,
        }

    def mark_reverification_for_source_revision(
        self,
        *,
        previous_document_id: str | None,
        replacement_document_id: str,
    ) -> list[DependencySuggestion]:
        if previous_document_id is None:
            return []
        updated: list[DependencySuggestion] = []
        for assertion in self.list_assertions(limit=10_000):
            if assertion.source_document_id != previous_document_id or assertion.needs_reverification:
                continue
            marked = assertion.model_copy(
                update={"needs_reverification": True, "state_version": assertion.state_version + 1}
            )
            self._graph.update_dependency_suggestion(marked)
            entry = self._audit.append(
                "dependency_assertion_reverification_requested",
                {
                    "assertion_id": marked.id,
                    "source_document_id": previous_document_id,
                    "replacement_document_id": replacement_document_id,
                    "edge_id": marked.suggested_edge.id if marked.decision is SuggestionDecision.CONFIRMED else None,
                },
                attribution=AuditAttribution(
                    actor_id="system:source-revision", correlation_id=marked.audit_correlation_id
                ),
            )
            marked = marked.model_copy(update={"reverification_audit_id": entry.entry_hash})
            self._graph.update_dependency_suggestion(marked)
            updated.append(marked)
        return updated

    def _source_document_for(
        self,
        source_item: KnowledgeItem,
        request: DependencyAssertionCreateRequest,
    ) -> SourceDocument:
        try:
            document = self._document_store.get_document(request.source_document_id)
            self._document_store.get_source(document.source_id)
        except (SourceDocumentNotFoundError, SourceNotFoundError) as exc:
            raise NotFoundError("registered source document was not found") from exc
        if document.version != request.source_document_version:
            raise BadRequestError("source document version does not match the immutable document record")
        provenance = source_item.metadata.get("source_document")
        if not isinstance(provenance, dict):
            raise BadRequestError("source knowledge item is not bound to a registered source document")
        if provenance.get("id") != document.id or provenance.get("version") != document.version:
            raise BadRequestError("source document is not the exact registered version for the source knowledge item")
        if request.evidence_kind is AssertionEvidenceKind.QUOTE:
            if request.quote is None or request.quote_start is None or request.quote_end is None:
                raise BadRequestError("quote evidence is incomplete")
            if (
                request.quote_end > len(document.content)
                or document.content[request.quote_start : request.quote_end] != request.quote
            ):
                raise BadRequestError(
                    "quote offsets do not reconstruct exactly from the immutable source document version"
                )
        return document

    def _resolve_target(
        self,
        source_item: KnowledgeItem,
        request: DependencyAssertionCreateRequest,
    ) -> tuple[str, EdgeType]:
        if request.target_kind == "knowledge_item":
            if request.target_item_id is None:
                raise BadRequestError("knowledge-item target is incomplete")
            target_item = self._get_item(request.target_item_id)
            if not _same_scope(source_item, target_item):
                raise PolicyRefusalError("dependency assertion cannot cross matter or client scope")
            return target_item.id, EdgeType.INTERNAL_DEPENDS_ON_INTERNAL
        if request.authority_source_id is None or request.authority_identifier is None:
            raise BadRequestError("external authority target is incomplete")
        try:
            authority_source = self._authority_sources.get(request.authority_source_id)
        except KeyError as exc:
            raise NotFoundError("registered authority source was not found") from exc
        if not authority_source.enabled:
            raise BadRequestError("registered authority source is disabled")
        if (authority_source.matter_id is not None and authority_source.matter_id != source_item.matter_id) or (
            authority_source.client_id is not None and authority_source.client_id != source_item.client_id
        ):
            raise PolicyRefusalError("registered authority target is outside the source item scope")
        target = self._authority_identifiers.resolve(authority_source, request.authority_identifier)
        return target.canonical_id, EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL

    def _transition(
        self,
        assertion: DependencySuggestion,
        decision: SuggestionDecision,
        *,
        by: str,
        reason: str | None,
    ) -> DependencySuggestion:
        if assertion.decision is decision:
            return assertion
        if assertion.decision is SuggestionDecision.CONFIRMED:
            raise BadRequestError("confirmed dependency assertions cannot be changed")
        if assertion.decision is SuggestionDecision.REJECTED and decision is not SuggestionDecision.WITHDRAWN:
            raise BadRequestError("rejected dependency assertions require a traced new assertion")
        if assertion.decision is SuggestionDecision.WITHDRAWN:
            raise BadRequestError("withdrawn dependency assertions cannot be changed")
        timestamp = datetime.now(timezone.utc)
        updated = assertion.model_copy(
            update={
                "decision": decision,
                "decided_by": by,
                "decided_at": timestamp,
                "decision_reason": reason,
                "withdrawn_at": timestamp if decision is SuggestionDecision.WITHDRAWN else None,
                "withdrawn_by": by if decision is SuggestionDecision.WITHDRAWN else None,
                "state_version": assertion.state_version + 1,
            }
        )
        self._graph.update_dependency_suggestion(updated)
        return self._schedule_transition(updated)

    def _get_assertion(self, assertion_id: str) -> DependencySuggestion:
        try:
            assertion = self._graph.get_dependency_suggestion(assertion_id)
        except KeyError as exc:
            raise NotFoundError("dependency assertion was not found") from exc
        if assertion.source not in {"human", "trusted_upstream"}:
            raise NotFoundError("dependency assertion was not found")
        return assertion

    def _by_idempotency(self, source: str, idempotency_key: str) -> DependencySuggestion | None:
        matches = self._graph.list_dependency_suggestions(source=source, limit=10_000)
        return next((item for item in matches if item.idempotency_key == idempotency_key), None)

    def _require_traced_successor(
        self,
        request: DependencyAssertionCreateRequest,
        *,
        source_item: KnowledgeItem,
        target_id: str,
        evidence_raw: str,
    ) -> None:
        prior = None
        if request.revision_of is not None:
            prior = self._get_assertion(request.revision_of)
            prior_item = self._get_item(prior.item_id)
            if not _same_scope(source_item, prior_item):
                raise PolicyRefusalError("assertion revision cannot cross matter or client scope")
            if prior.source_document_id != request.source_document_id:
                try:
                    revision_document = self._document_store.get_document(request.source_document_id)
                except SourceDocumentNotFoundError as exc:
                    raise NotFoundError("registered source document was not found") from exc
                if revision_document.previous_version_id != prior.source_document_id:
                    raise BadRequestError("assertion revision must point to the immediately preceding source version")
        matching_terminal = next(
            (
                assertion
                for assertion in self.list_assertions(item_id=request.item_id, target_id=target_id, limit=10_000)
                if assertion.assertion_type == request.assertion_type
                and assertion.evidence_raw == evidence_raw
                and assertion.decision in {SuggestionDecision.REJECTED, SuggestionDecision.WITHDRAWN}
            ),
            None,
        )
        if matching_terminal is not None and request.revision_of != matching_terminal.id:
            raise BadRequestError("a rejected or withdrawn assertion requires a traceable revision_of reference")
        if prior is not None and prior.id == request.idempotency_key:
            raise BadRequestError("revision_of cannot equal the new idempotency key")

    def _in_scope(self, assertion: DependencySuggestion, *, matter_id: str | None, client_id: str | None) -> bool:
        try:
            source_item = self._get_item(assertion.item_id)
        except NotFoundError:
            return False
        return (matter_id is None or source_item.matter_id == matter_id) and (
            client_id is None or source_item.client_id == client_id
        )

    def _require_scope(self, assertion: DependencySuggestion, *, matter_id: str | None, client_id: str | None) -> None:
        if not self._in_scope(assertion, matter_id=matter_id, client_id=client_id):
            raise NotFoundError("dependency assertion was not found")

    def _check_version(self, assertion: DependencySuggestion, expected: int | None) -> None:
        if expected is not None and expected != assertion.state_version:
            raise ConflictError("dependency assertion state version is stale")

    def _require_separation_of_duties(self, assertion: DependencySuggestion, *, reviewer: str) -> None:
        if assertion.created_by != reviewer:
            return
        entry = self._audit.append(
            "dependency_assertion_separation_of_duties_denied",
            {"assertion_id": assertion.id, "creator": assertion.created_by, "reviewer": reviewer},
            attribution=AuditAttribution(actor_id=reviewer, correlation_id=assertion.audit_correlation_id),
        )
        raise PolicyRefusalError(
            "dependency assertion creator cannot confirm or decide their own assertion",
            details={"audit_id": entry.entry_hash},
        )


def _same_scope(source: KnowledgeItem, target: KnowledgeItem) -> bool:
    return source.matter_id == target.matter_id and source.client_id == target.client_id


def _request_sha256(request: DependencyAssertionCreateRequest) -> str:
    payload = request.model_dump(mode="json")
    payload.pop("correlation_id", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def evidence_raw_for(request: DependencyAssertionCreateRequest) -> str:
    return request.quote or "" if request.evidence_kind is AssertionEvidenceKind.QUOTE else request.commentary or ""


def _assertion_audit_payload(assertion: DependencySuggestion) -> dict[str, Any]:
    return {
        "assertion_id": assertion.id,
        "item_id": assertion.item_id,
        "target_id": assertion.suggested_edge.target_id,
        "target_kind": assertion.suggested_edge.target_kind,
        "assertion_type": assertion.assertion_type.value if assertion.assertion_type is not None else None,
        "origin": assertion.source,
        "state": assertion.decision.value,
        "creator": assertion.created_by,
        "source_resource_id": assertion.source_resource_id,
        "source_document_id": assertion.source_document_id,
        "source_document_version": assertion.source_document_version,
        "source_document_sha256": assertion.source_document_sha256,
        "evidence_kind": assertion.evidence_kind.value if assertion.evidence_kind is not None else None,
        "evidence_sha256": hashlib.sha256((assertion.evidence_raw or "").encode()).hexdigest(),
        "rationale_sha256": hashlib.sha256((assertion.rationale or "").encode()).hexdigest(),
        "state_version": assertion.state_version,
    }
