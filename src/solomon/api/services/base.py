# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from solomon.api.service_models import (
    DependencySuggestionDecisionRequest,
    PrimitivePlanExecution,
    PrimitivePlanRequest,
    RecallRequest,
    VerificationAssignmentRequest,
    VerificationRequest,
    VerificationReviewRequest,
    WhyTrace,
)
from solomon.audit.journal import AuditJournal
from solomon.boundary.solomon import SolomonBoundary
from solomon.credence.policy import CredenceLedger
from solomon.currency.cache import CurrencyEvaluationCache
from solomon.currency.models import KnowledgeItem
from solomon.graph.suggestions import DependencySuggestion
from solomon.graph.types import DependencyGraphProtocol
from solomon.orchestrator.models import ModelRequest, ModelRouter, RoutedModelResult
from solomon.orchestrator.retrieval import RetrievalIndexProtocol, RetrievalOrchestrator
from solomon.store.types import KnowledgeStoreProtocol


class ServiceContext(Protocol):
    store: KnowledgeStoreProtocol
    graph: DependencyGraphProtocol
    operation_store: Any
    tenant_id: str | None
    index: RetrievalIndexProtocol
    credence: CredenceLedger
    currency_cache: CurrencyEvaluationCache
    retrieval: RetrievalOrchestrator
    audit: AuditJournal
    attestation_key: str | None
    boundary: SolomonBoundary
    document_store: Any
    authority_sources: Any
    authority_identifiers: Any
    verification_policy_version: str
    credence_policy_version: str

    def _get_item(self, item_id: str) -> KnowledgeItem: ...

    def _persist_credence_entries(self, *, start: int) -> None: ...

    def _deterministic_store_timestamp(self) -> datetime: ...

    def _store_state_sha256(self) -> str: ...

    def _create_dependency_suggestions(
        self,
        item: KnowledgeItem,
        *,
        use_llm: bool = False,
        router: ModelRouter | None = None,
    ) -> list[DependencySuggestion]: ...

    def defer_dependency_suggestion(
        self,
        suggestion_id: str,
        request: DependencySuggestionDecisionRequest,
    ) -> DependencySuggestion: ...

    def recall(self, request: RecallRequest) -> list[dict[str, Any]]: ...

    def evaluate_currency(self, item_id: str, *, as_of: datetime | None = None) -> dict[str, Any]: ...

    def impact_query(self, authority_id: str, *, as_of: datetime | None = None) -> dict[str, Any]: ...

    def timeline(self, request: RecallRequest, *, as_of: str) -> list[dict[str, Any]]: ...

    def record_verification(self, item_id: str, request: VerificationRequest) -> KnowledgeItem: ...

    def assign_verification(self, item_id: str, request: VerificationAssignmentRequest) -> KnowledgeItem: ...

    def start_verification_review(self, item_id: str, request: VerificationReviewRequest) -> KnowledgeItem: ...

    def why(self, item_id: str, *, as_of: datetime | None = None) -> WhyTrace: ...

    def execute_plan(self, request: PrimitivePlanRequest) -> PrimitivePlanExecution: ...

    def complete_model_request(
        self,
        router: ModelRouter,
        request: ModelRequest,
        *,
        matter: Any | None = None,
    ) -> RoutedModelResult: ...


class ServiceDelegate:
    def __init__(self, context: ServiceContext) -> None:
        self._context = context

    @property
    def store(self) -> KnowledgeStoreProtocol:
        return self._context.store

    @property
    def graph(self) -> DependencyGraphProtocol:
        return self._context.graph

    @property
    def operation_store(self) -> Any:
        return self._context.operation_store

    @property
    def tenant_id(self) -> str | None:
        return self._context.tenant_id

    @property
    def index(self) -> RetrievalIndexProtocol:
        return self._context.index

    @property
    def credence(self) -> CredenceLedger:
        return self._context.credence

    @property
    def currency_cache(self) -> CurrencyEvaluationCache:
        return self._context.currency_cache

    @property
    def retrieval(self) -> RetrievalOrchestrator:
        return self._context.retrieval

    @property
    def audit(self) -> AuditJournal:
        return self._context.audit

    @property
    def attestation_key(self) -> str | None:
        return self._context.attestation_key

    @property
    def boundary(self) -> SolomonBoundary:
        return self._context.boundary

    @property
    def document_store(self) -> Any:
        return self._context.document_store

    @property
    def authority_sources(self) -> Any:
        return self._context.authority_sources

    @property
    def authority_identifiers(self) -> Any:
        return self._context.authority_identifiers

    @property
    def verification_policy_version(self) -> str:
        return self._context.verification_policy_version

    @property
    def credence_policy_version(self) -> str:
        return self._context.credence_policy_version

    def _get_item(self, item_id: str) -> KnowledgeItem:
        return self._context._get_item(item_id)

    def _persist_credence_entries(self, *, start: int) -> None:
        self._context._persist_credence_entries(start=start)

    def _deterministic_store_timestamp(self) -> datetime:
        return self._context._deterministic_store_timestamp()

    def _store_state_sha256(self) -> str:
        return self._context._store_state_sha256()

    def _create_dependency_suggestions(
        self,
        item: KnowledgeItem,
        *,
        use_llm: bool = False,
        router: ModelRouter | None = None,
    ) -> list[DependencySuggestion]:
        return self._context._create_dependency_suggestions(item, use_llm=use_llm, router=router)

    def defer_dependency_suggestion(
        self,
        suggestion_id: str,
        request: DependencySuggestionDecisionRequest,
    ) -> DependencySuggestion:
        return self._context.defer_dependency_suggestion(suggestion_id, request)

    def recall(self, request: RecallRequest) -> list[dict[str, Any]]:
        return self._context.recall(request)

    def evaluate_currency(self, item_id: str, *, as_of: datetime | None = None) -> dict[str, Any]:
        return self._context.evaluate_currency(item_id, as_of=as_of)

    def impact_query(self, authority_id: str, *, as_of: datetime | None = None) -> dict[str, Any]:
        return self._context.impact_query(authority_id, as_of=as_of)

    def timeline(self, request: RecallRequest, *, as_of: str) -> list[dict[str, Any]]:
        return self._context.timeline(request, as_of=as_of)

    def record_verification(self, item_id: str, request: VerificationRequest) -> KnowledgeItem:
        return self._context.record_verification(item_id, request)

    def assign_verification(self, item_id: str, request: VerificationAssignmentRequest) -> KnowledgeItem:
        return self._context.assign_verification(item_id, request)

    def start_verification_review(self, item_id: str, request: VerificationReviewRequest) -> KnowledgeItem:
        return self._context.start_verification_review(item_id, request)

    def why(self, item_id: str, *, as_of: datetime | None = None) -> WhyTrace:
        return self._context.why(item_id, as_of=as_of)

    def execute_plan(self, request: PrimitivePlanRequest) -> PrimitivePlanExecution:
        return self._context.execute_plan(request)

    def complete_model_request(
        self,
        router: ModelRouter,
        request: ModelRequest,
        *,
        matter: Any | None = None,
    ) -> RoutedModelResult:
        return self._context.complete_model_request(router, request, matter=matter)
