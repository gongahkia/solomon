# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.audit.journal import AuditJournal, sign_verification_attestation
from solomon.credence.policy import CredenceLedger
from solomon.currency.cache import CurrencyEvaluationCache
from solomon.currency.engine import (
    VerificationOutcome,
    evaluate_currency,
    record_verification,
    register_authority_change,
)
from solomon.currency.models import KnowledgeItem, KnowledgeKind, Provenance, SourceKind
from solomon.currency.prediction import PendingAuthorityAmendment, StalenessRiskReport, predict_staleness_risk
from solomon.errors import NotFoundError
from solomon.graph.models import DependencyEdge, EdgeConfidence, EdgeType
from solomon.graph.propagation import CurrencyPropagator
from solomon.graph.store import GraphStore
from solomon.graph.suggestions import ReferenceExtraction, extract_defined_terms_and_citations
from solomon.graph.visualization import GraphFormat, dependency_graph_view, render_dependency_graph
from solomon.orchestrator.retrieval import MatterContext, RecallOptions, RetrievalOrchestrator, SQLiteRetrievalIndex
from solomon.store.sqlite import ItemNotFoundError, SQLiteKnowledgeStore


class IngestRequest(SolomonModel):
    kind: KnowledgeKind
    content: str = Field(min_length=1)
    source_kind: SourceKind
    source_ref: str = Field(min_length=1)
    author: str | None = None
    matter_id: str | None = None
    client_id: str | None = None


class RecallRequest(SolomonModel):
    query: str
    matter_id: str | None = None
    client_id: str | None = None
    review_mode: bool = False
    limit: int = 10
    max_context_tokens: int | None = Field(default=None, ge=1)


class VerificationRequest(SolomonModel):
    by: str
    outcome: VerificationOutcome
    successor_id: str | None = None


class AuthorityChangeRequest(SolomonModel):
    new_version: str
    changed_at: str


class ReferenceExtractionRequest(SolomonModel):
    content: str = Field(min_length=1)


class StalenessPredictionRequest(SolomonModel):
    pending_amendments: list[PendingAuthorityAmendment]
    lookahead_days: int = Field(default=180, ge=1)
    as_of: str | None = None


class DependencyRequest(SolomonModel):
    source_id: str
    target_id: str
    edge_type: EdgeType
    target_kind: str
    confidence: EdgeConfidence = EdgeConfidence.HUMAN_ASSERTED
    created_by: str | None = None
    reason: str | None = None


class WhyTrace(SolomonModel):
    item: KnowledgeItem
    currency: dict[str, Any]
    dependencies: list[dict[str, Any]]
    dependents: list[dict[str, Any]]
    provenance: dict[str, Any]
    credence_tier: str
    verification: dict[str, Any]


class SolomonService:
    def __init__(self, *, data_dir: Path, journal_dir: Path, attestation_key: str | None = None) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        journal_dir.mkdir(parents=True, exist_ok=True)
        db = data_dir / "solomon.sqlite3"
        self.store = SQLiteKnowledgeStore(db)
        self.graph = GraphStore(db)
        self.index = SQLiteRetrievalIndex(db)
        self.credence = CredenceLedger()
        self.currency_cache = CurrencyEvaluationCache()
        self.retrieval = RetrievalOrchestrator(
            store=self.store,
            graph=self.graph,
            index=self.index,
            credence=self.credence,
        )
        self.audit = AuditJournal(journal_dir / "journal.jsonl")
        self.attestation_key = attestation_key

    def ingest(self, request: IngestRequest) -> KnowledgeItem:
        item = KnowledgeItem(
            kind=request.kind,
            content=request.content,
            provenance=Provenance(
                source_kind=request.source_kind,
                source_ref=request.source_ref,
                author=request.author,
                matter_id=request.matter_id,
            ),
            matter_id=request.matter_id,
            client_id=request.client_id,
        )
        item = self.credence.assign_on_ingest(item)
        item = self.index.upsert_item(item)
        self.store.write_item(item)
        return item

    def recall(self, request: RecallRequest) -> list[dict[str, Any]]:
        results = self.retrieval.recall(
            request.query,
            matter_context=MatterContext(matter_id=request.matter_id, client_id=request.client_id),
            options=RecallOptions(
                limit=request.limit,
                review_mode=request.review_mode,
                max_context_tokens=request.max_context_tokens,
            ),
        )
        self.audit.log_query(query_id=request.query, results=results)
        return [result.model_dump(mode="json") for result in results]

    def evaluate_currency(self, item_id: str) -> dict[str, Any]:
        return self.currency_cache.get_or_evaluate(self._get_item(item_id)).model_dump(mode="json")

    def record_verification(self, item_id: str, request: VerificationRequest) -> KnowledgeItem:
        item = self._get_item(item_id)
        recorded = record_verification(
            item,
            by=request.by,
            outcome=request.outcome,
            successor_id=request.successor_id,
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

    def impact_query(self, authority_id: str) -> dict[str, Any]:
        return CurrencyPropagator(graph=self.graph, store=self.store).impact_query(authority_id).model_dump(mode="json")

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
        from datetime import datetime

        return predict_staleness_risk(
            request.pending_amendments,
            graph=self.graph,
            store=self.store,
            as_of=datetime.fromisoformat(request.as_of) if request.as_of else None,
            lookahead_days=request.lookahead_days,
        )

    def why(self, item_id: str) -> WhyTrace:
        item = self._get_item(item_id)
        return WhyTrace(
            item=item,
            currency=evaluate_currency(item).model_dump(mode="json"),
            dependencies=[edge.model_dump(mode="json") for edge in self.graph.get_dependencies(item.id)],
            dependents=[edge.model_dump(mode="json") for edge in self.graph.get_dependents(item.id)],
            provenance=item.provenance.model_dump(mode="json"),
            credence_tier=item.credence_tier.value,
            verification={
                "verified_state": item.verified_state.value,
                "last_verified_at": item.last_verified_at.isoformat() if item.last_verified_at else None,
                "verified_by": item.verified_by,
            },
        )

    def timeline(self, request: RecallRequest, *, as_of: str) -> list[dict[str, Any]]:
        from datetime import datetime

        results = self.retrieval.timeline(
            request.query,
            as_of=datetime.fromisoformat(as_of),
            options=RecallOptions(
                limit=request.limit,
                review_mode=True,
                max_context_tokens=request.max_context_tokens,
            ),
        )
        return [result.model_dump(mode="json") for result in results]

    def export_audit_pack(self, destination: Path) -> Path:
        return self.audit.export_pack(destination).directory

    def _get_item(self, item_id: str) -> KnowledgeItem:
        try:
            return self.store.get_item(item_id)
        except ItemNotFoundError as exc:
            raise NotFoundError(f"knowledge item not found: {item_id}") from exc
