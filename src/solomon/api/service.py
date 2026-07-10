# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from solomon.api.service_models import (
    AffirmRequest,
    AffirmResponse,
    AnswerRequest,
    AnswerResponse,
    AuthorityChangeRequest,
    ContestRequest,
    ContestResponse,
    DependencyRequest,
    DependencySuggestionDecisionRequest,
    DependencySuggestionRequest,
    IngestRequest,
    PinRequest,
    PrimitivePlanExecution,
    PrimitivePlanRequest,
    PrimitivePlanStep,
    PrimitiveStepResult,
    RecallRequest,
    ReferenceExtractionRequest,
    StalenessPredictionRequest,
    VerificationAssignmentRequest,
    VerificationRequest,
    VerificationReviewRequest,
    WhyTrace,
)
from solomon.api.services.answer import AnswerService
from solomon.api.services.authority import AuthorityService
from solomon.api.services.common import digest
from solomon.api.services.ingestion import IngestionService
from solomon.api.services.recall import RecallService
from solomon.audit.journal import AuditJournal
from solomon.boundary.solomon import SolomonBoundary
from solomon.credence.policy import CredenceLedger, CredencePolicy
from solomon.currency.cache import CurrencyEvaluationCache
from solomon.currency.contradiction import ContradictionSignal, contradictions_for_item
from solomon.currency.engine import VerificationPolicy, record_verification
from solomon.currency.models import KnowledgeItem
from solomon.currency.prediction import StalenessRiskReport
from solomon.currency.verification import verification_history
from solomon.errors import NotFoundError
from solomon.graph.models import DependencyEdge
from solomon.graph.suggestions import DependencySuggestion, ReferenceExtraction, SuggestionDecision
from solomon.graph.visualization import GraphFormat
from solomon.orchestrator.models import ModelRequest, ModelRouter, RoutedModelResult
from solomon.orchestrator.retrieval import RetrievalOrchestrator
from solomon.store.factory import create_storage_bundle
from solomon.store.sqlite import ItemNotFoundError


class SolomonService:
    def __init__(
        self,
        *,
        data_dir: Path,
        journal_dir: Path,
        attestation_key: str | None = None,
        boundary: SolomonBoundary | None = None,
        database_url: str | None = None,
        postgres_schema: str | None = None,
        verification_policy: VerificationPolicy | None = None,
        verification_policy_version: str = "verification-policy.v1",
        credence_policy: CredencePolicy | None = None,
        credence_policy_version: str = "credence-policy.v1",
    ) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        journal_dir.mkdir(parents=True, exist_ok=True)
        storage = create_storage_bundle(
            database_url or str(data_dir / "solomon.sqlite3"),
            postgres_schema=postgres_schema,
        )
        self.store = storage.store
        self.graph = storage.graph
        self.index = storage.index
        self.verification_policy = verification_policy or VerificationPolicy()
        self.verification_policy_version = verification_policy_version
        self.credence_policy_version = credence_policy_version
        self.credence = CredenceLedger(policy=credence_policy)
        self.currency_cache = CurrencyEvaluationCache(policy=self.verification_policy)
        self.retrieval = RetrievalOrchestrator(
            store=self.store,
            graph=self.graph,
            index=self.index,
            credence=self.credence,
        )
        self.audit = AuditJournal(journal_dir / "journal.jsonl")
        self.attestation_key = attestation_key
        self.boundary = boundary or SolomonBoundary()
        self._ingestion = IngestionService(self)
        self._answer = AnswerService(self)
        self._authority = AuthorityService(self)
        self._recall = RecallService(self)

    def ingest(self, request: IngestRequest) -> KnowledgeItem:
        return self._ingestion.ingest(request)

    def recall(self, request: RecallRequest) -> list[dict[str, Any]]:
        return self._recall.recall(request)

    def answer(self, request: AnswerRequest, router: ModelRouter) -> AnswerResponse:
        return self._answer.answer(request, router)

    def complete_model_request(
        self,
        router: ModelRouter,
        request: ModelRequest,
        *,
        matter: Any | None = None,
    ) -> RoutedModelResult:
        return self._answer.complete_model_request(router, request, matter=matter)

    def evaluate_currency(self, item_id: str, *, as_of: datetime | None = None) -> dict[str, Any]:
        return self._authority.evaluate_currency(item_id, as_of=as_of)

    def record_verification(self, item_id: str, request: VerificationRequest) -> KnowledgeItem:
        return self._authority.record_verification(item_id, request)

    def assign_verification(self, item_id: str, request: VerificationAssignmentRequest) -> KnowledgeItem:
        return self._authority.assign_verification(item_id, request)

    def start_verification_review(self, item_id: str, request: VerificationReviewRequest) -> KnowledgeItem:
        return self._authority.start_verification_review(item_id, request)

    def verification_queue(
        self,
        *,
        reviewer_id: str | None = None,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._authority.verification_queue(
            reviewer_id=reviewer_id,
            matter_id=matter_id,
            client_id=client_id,
        )

    def detect_contradictions(
        self,
        *,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> list[ContradictionSignal]:
        return self._authority.detect_contradictions(matter_id=matter_id, client_id=client_id)

    def register_authority_change(self, authority_id: str, request: AuthorityChangeRequest) -> dict[str, Any]:
        return self._authority.register_authority_change(authority_id, request)

    def contest(self, item_id: str, request: ContestRequest) -> ContestResponse:
        return self._ingestion.contest(item_id, request)

    def affirm(self, item_id: str, request: AffirmRequest) -> AffirmResponse:
        return self._ingestion.affirm(item_id, request)

    def pin(self, item_id: str, request: PinRequest) -> KnowledgeItem:
        return self._ingestion.pin(item_id, request)

    def add_dependency(self, request: DependencyRequest) -> DependencyEdge:
        return self._authority.add_dependency(request)

    def suggest_dependencies(
        self,
        request: DependencySuggestionRequest,
        *,
        router: ModelRouter | None = None,
    ) -> list[DependencySuggestion]:
        return self._authority.suggest_dependencies(request, router=router)

    def dependency_suggestions(
        self,
        *,
        item_id: str | None = None,
        decision: SuggestionDecision | None = None,
        limit: int = 100,
    ) -> list[DependencySuggestion]:
        return self._authority.dependency_suggestions(item_id=item_id, decision=decision, limit=limit)

    def confirm_dependency_suggestion(
        self,
        suggestion_id: str,
        request: DependencySuggestionDecisionRequest,
    ) -> DependencyEdge:
        return self._authority.confirm_dependency_suggestion(suggestion_id, request)

    def reject_dependency_suggestion(
        self,
        suggestion_id: str,
        request: DependencySuggestionDecisionRequest,
    ) -> DependencySuggestion:
        return self._authority.reject_dependency_suggestion(suggestion_id, request)

    def impact_query(self, authority_id: str, *, as_of: datetime | None = None) -> dict[str, Any]:
        return self._authority.impact_query(authority_id, as_of=as_of)

    def dependency_graph(
        self,
        *,
        output_format: GraphFormat = "mermaid",
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> str:
        return self._authority.dependency_graph(
            output_format=output_format,
            matter_id=matter_id,
            client_id=client_id,
        )

    def extract_references(self, request: ReferenceExtractionRequest) -> ReferenceExtraction:
        return self._authority.extract_references(request)

    def predict_staleness(self, request: StalenessPredictionRequest) -> StalenessRiskReport:
        return self._authority.predict_staleness(request)

    def why(self, item_id: str, *, as_of: datetime | None = None) -> WhyTrace:
        return self._recall.why(item_id, as_of=as_of)

    def timeline(self, request: RecallRequest, *, as_of: str) -> list[dict[str, Any]]:
        return self._recall.timeline(request, as_of=as_of)

    def execute_plan(self, request: PrimitivePlanRequest) -> PrimitivePlanExecution:
        return self._recall.execute_plan(request)

    def export_audit_pack(self, destination: Path) -> Path:
        pack = self.audit.export_pack(destination)
        histories = {
            item.id: [event.model_dump(mode="json") for event in verification_history(item)]
            for item in self.store.get_many()
            if verification_history(item)
        }
        history_path = pack.directory / "verification-history.json"
        history_bytes = json.dumps(histories, sort_keys=True, indent=2).encode("utf-8")
        history_path.write_bytes(history_bytes)
        contradictions = {
            item.id: [signal.model_dump(mode="json") for signal in contradictions_for_item(item)]
            for item in self.store.get_many()
            if contradictions_for_item(item)
        }
        contradictions_path = pack.directory / "contradictions.json"
        contradictions_bytes = json.dumps(contradictions, sort_keys=True, indent=2).encode("utf-8")
        contradictions_path.write_bytes(contradictions_bytes)
        manifest = json.loads(pack.manifest_path.read_text(encoding="utf-8"))
        manifest.pop("manifest_sha256", None)
        manifest["verification_history_file"] = history_path.name
        manifest["verification_history_sha256"] = hashlib.sha256(history_bytes).hexdigest()
        manifest["contradictions_file"] = contradictions_path.name
        manifest["contradictions_sha256"] = hashlib.sha256(contradictions_bytes).hexdigest()
        manifest_bytes = json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8")
        manifest["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
        pack.manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
        return pack.directory

    def _create_dependency_suggestions(
        self,
        item: KnowledgeItem,
        *,
        use_llm: bool = False,
        router: ModelRouter | None = None,
    ) -> list[DependencySuggestion]:
        return self._authority._create_dependency_suggestions(item, use_llm=use_llm, router=router)

    def _store_state_sha256(self) -> str:
        items = []
        for item in sorted(self.store.get_many(), key=lambda current: current.id):
            items.append(
                {
                    "id": item.id,
                    "content_sha256": hashlib.sha256(item.content.encode("utf-8")).hexdigest(),
                    "currency_state": item.currency_state.value,
                    "credence_tier": item.credence_tier.value,
                    "verified_state": item.verified_state.value,
                    "last_verified_at": item.last_verified_at.isoformat() if item.last_verified_at else None,
                    "valid_from": item.valid_from.isoformat(),
                    "valid_to": item.valid_to.isoformat() if item.valid_to else None,
                    "successor_id": item.successor_id,
                    "metadata": item.metadata,
                }
            )
        edges = [
            edge.model_dump(mode="json")
            for edge in sorted(
                self.graph.subgraph_for_scope(store=self.store),
                key=lambda current: current.id,
            )
        ]
        return digest({"items": items, "edges": edges})

    def _deterministic_store_timestamp(self) -> datetime:
        timestamps: list[datetime] = []
        for item in self.store.get_many():
            timestamps.extend([item.valid_from, item.ingested_at])
            if item.last_verified_at is not None:
                timestamps.append(item.last_verified_at)
            if item.valid_to is not None:
                timestamps.append(item.valid_to)
        return max(timestamps) if timestamps else datetime(1970, 1, 1, tzinfo=timezone.utc)

    def _get_item(self, item_id: str) -> KnowledgeItem:
        try:
            return self.store.get_item(item_id)
        except ItemNotFoundError as exc:
            raise NotFoundError(f"knowledge item not found: {item_id}") from exc

    def _persist_credence_entries(self, *, start: int) -> None:
        for entry in self.credence.entries[start:]:
            self.audit.log_credence_change(entry)


__all__ = [
    "SolomonService",
    "IngestRequest",
    "RecallRequest",
    "VerificationRequest",
    "VerificationAssignmentRequest",
    "VerificationReviewRequest",
    "AuthorityChangeRequest",
    "ContestRequest",
    "ContestResponse",
    "AffirmRequest",
    "AffirmResponse",
    "PinRequest",
    "ReferenceExtractionRequest",
    "StalenessPredictionRequest",
    "DependencyRequest",
    "DependencySuggestionRequest",
    "DependencySuggestionDecisionRequest",
    "AnswerRequest",
    "AnswerResponse",
    "WhyTrace",
    "PrimitivePlanStep",
    "PrimitivePlanRequest",
    "PrimitiveStepResult",
    "PrimitivePlanExecution",
    "record_verification",
]
