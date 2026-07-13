# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
from base64 import b64decode
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from solomon.api.service_models import (
    AffirmRequest,
    AffirmResponse,
    AnswerRequest,
    AnswerResponse,
    AuthorityChangeRequest,
    AuthorityEventRequest,
    CandidateClaimDeferralRequest,
    CandidateClaimPromotionRequest,
    CandidateClaimRejectionRequest,
    ContestRequest,
    ContestResponse,
    DependencyRequest,
    DependencySuggestionDecisionRequest,
    DependencySuggestionRequest,
    DocumentSourceRequest,
    IngestRequest,
    PinRequest,
    PrimitivePlanExecution,
    PrimitivePlanRequest,
    PrimitivePlanStep,
    PrimitiveStepResult,
    RecallRequest,
    ReferenceExtractionRequest,
    ReviewTaskAssignmentRequest,
    ReviewTaskResolutionRequest,
    ReviewTaskStartRequest,
    SourceDocumentIngestRequest,
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
from solomon.currency.models import KnowledgeItem, KnowledgeKind, now_utc
from solomon.currency.prediction import StalenessRiskReport
from solomon.currency.report import (
    CurrencyMovementReport,
    ReportScopeKind,
    currency_movement_report,
    render_currency_report_pdf,
)
from solomon.currency.verification import verification_history
from solomon.errors import BadRequestError, NotFoundError
from solomon.graph.models import DependencyEdge
from solomon.graph.suggestions import DependencySuggestion, ReferenceExtraction, SuggestionDecision
from solomon.graph.visualization import GraphFormat
from solomon.orchestrator.models import ModelRequest, ModelRouter, RoutedModelResult
from solomon.orchestrator.retrieval import RetrievalOrchestrator
from solomon.sources.extract import candidate_claims_from_text, extract_document_bytes
from solomon.sources.models import CandidateClaim, CandidateClaimStatus, DocumentSource, SourceDocument
from solomon.sources.store import CandidateClaimNotFoundError, SourceDocumentNotFoundError, SQLiteDocumentStore
from solomon.store.factory import create_storage_bundle
from solomon.store.sqlite import ItemNotFoundError
from solomon.workflow.models import AuthorityChangeEvent, ReviewTask, ReviewTaskPriority, ReviewTaskState
from solomon.workflow.store import SQLiteWorkflowStore


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
        self.document_store = SQLiteDocumentStore(data_dir / "sources.sqlite3")
        self.workflow_store = SQLiteWorkflowStore(data_dir / "workflow.sqlite3")
        self.attestation_key = attestation_key
        self.boundary = boundary or SolomonBoundary()
        self._ingestion = IngestionService(self)
        self._answer = AnswerService(self)
        self._authority = AuthorityService(self)
        self._recall = RecallService(self)

    def ingest(self, request: IngestRequest) -> KnowledgeItem:
        return self._ingestion.ingest(request)

    def register_document_source(self, request: DocumentSourceRequest) -> DocumentSource:
        source = DocumentSource(
            name=request.name,
            kind=request.kind,
            root_ref=request.root_ref,
            enabled=request.enabled,
            config=request.config,
        )
        if request.source_id is not None:
            try:
                existing = self.document_store.get_source(request.source_id)
            except KeyError:
                source = source.model_copy(update={"id": request.source_id})
            else:
                if (
                    existing.name == source.name
                    and existing.kind is source.kind
                    and existing.root_ref == source.root_ref
                    and existing.enabled is source.enabled
                    and existing.config == source.config
                ):
                    return existing
                source = source.model_copy(update={"id": existing.id, "created_at": existing.created_at})
        stored = self.document_store.upsert_source(source)
        self.audit.append(
            "document_source_registered",
            {"source_id": stored.id, "kind": stored.kind.value, "root_ref_sha256": digest(stored.root_ref)},
        )
        return stored

    def source_documents(self, source_id: str) -> list[SourceDocument]:
        self.document_store.get_source(source_id)
        return self.document_store.list_documents(source_id)

    def ingest_source_document(
        self,
        source_id: str,
        request: SourceDocumentIngestRequest,
    ) -> tuple[SourceDocument, list[CandidateClaim]]:
        source = self.document_store.get_source(source_id)
        if not source.enabled:
            raise BadRequestError("document source is disabled")
        try:
            if request.content_base64 is not None:
                raw = b64decode(request.content_base64, validate=True)
            else:
                if request.content is None:
                    raise BadRequestError("content is required when content_base64 is omitted")
                raw = request.content.encode("utf-8")
        except ValueError as exc:
            raise BadRequestError("content_base64 must be valid base64") from exc
        extracted = extract_document_bytes(raw, filename=request.filename, mime_type=request.mime_type)
        document = self.document_store.write_document(
            SourceDocument(
                source_id=source_id,
                external_id=request.external_id,
                filename=request.filename,
                mime_type=extracted.mime_type,
                content=extracted.text,
                extraction_state=extracted.state,
                extraction_reason=extracted.reason,
                metadata={**request.metadata, "extraction": extracted.metadata},
            )
        )
        candidates = self.document_store.list_candidates(document.id)
        if document.extraction_state.value == "ready" and not candidates:
            candidates = [
                self.document_store.add_candidate(
                    CandidateClaim(document_id=document.id, content=content, start_offset=start, end_offset=end)
                )
                for content, start, end in candidate_claims_from_text(document.content)
            ]
        self.audit.append(
            "source_document_ingested",
            {
                "source_id": source_id,
                "document_id": document.id,
                "external_id_sha256": digest(document.external_id),
                "version": document.version,
                "content_sha256": document.content_sha256,
                "extraction_state": document.extraction_state.value,
                "candidate_count": len(candidates),
            },
        )
        return document, candidates

    def candidate_claims(self, document_id: str) -> list[CandidateClaim]:
        self.document_store.get_document(document_id)
        return self.document_store.list_candidates(document_id)

    def promote_candidate_claim(self, candidate_id: str, request: CandidateClaimPromotionRequest) -> KnowledgeItem:
        try:
            candidate = self.document_store.get_candidate(candidate_id)
        except CandidateClaimNotFoundError as exc:
            raise NotFoundError(f"candidate claim not found: {candidate_id}") from exc
        if candidate.status is not CandidateClaimStatus.PENDING:
            raise BadRequestError("only pending candidate claims can be promoted")
        try:
            document = self.document_store.get_document(candidate.document_id)
        except SourceDocumentNotFoundError as exc:
            raise NotFoundError(f"source document not found: {candidate.document_id}") from exc
        if document.extraction_state.value != "ready":
            raise BadRequestError("candidate source document is not extractable")
        item = self.ingest(
            IngestRequest(
                kind=request.kind,
                content=candidate.content,
                source_kind=request.source_kind,
                source_ref=f"source-document:{document.source_id}:{document.external_id}:v{document.version}",
                author=request.author or request.by,
                matter_id=request.matter_id,
                client_id=request.client_id,
                conclusion=request.conclusion,
                conclusion_polarity=request.conclusion_polarity,
            )
        )
        self.document_store.update_candidate(
            candidate.model_copy(
                update={
                    "status": CandidateClaimStatus.PROMOTED,
                    "promotion_item_id": item.id,
                    "decision_by": request.by,
                    "decided_at": now_utc(),
                }
            )
        )
        self.audit.append(
            "candidate_claim_promoted",
            {"candidate_id": candidate_id, "document_id": document.id, "item_id": item.id, "by": request.by},
        )
        return item

    def reject_candidate_claim(self, candidate_id: str, request: CandidateClaimRejectionRequest) -> CandidateClaim:
        try:
            candidate = self.document_store.get_candidate(candidate_id)
        except CandidateClaimNotFoundError as exc:
            raise NotFoundError(f"candidate claim not found: {candidate_id}") from exc
        if candidate.status is not CandidateClaimStatus.PENDING:
            raise BadRequestError("only pending candidate claims can be rejected")
        rejected = self.document_store.update_candidate(
            candidate.model_copy(
                update={
                    "status": CandidateClaimStatus.REJECTED,
                    "decision_by": request.by,
                    "decision_reason": request.reason,
                    "decided_at": now_utc(),
                }
            )
        )
        self.audit.append(
            "candidate_claim_rejected",
            {"candidate_id": candidate_id, "document_id": candidate.document_id, "by": request.by},
        )
        return rejected

    def defer_candidate_claim(self, candidate_id: str, request: CandidateClaimDeferralRequest) -> CandidateClaim:
        try:
            candidate = self.document_store.get_candidate(candidate_id)
        except CandidateClaimNotFoundError as exc:
            raise NotFoundError(f"candidate claim not found: {candidate_id}") from exc
        if candidate.status is not CandidateClaimStatus.PENDING:
            raise BadRequestError("only pending candidate claims can be deferred")
        deferred = self.document_store.update_candidate(
            candidate.model_copy(
                update={
                    "status": CandidateClaimStatus.DEFERRED,
                    "decision_by": request.by,
                    "decision_reason": request.reason,
                    "decided_at": now_utc(),
                }
            )
        )
        self.audit.append(
            "candidate_claim_deferred",
            {"candidate_id": candidate_id, "document_id": candidate.document_id, "by": request.by},
        )
        return deferred

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

    def register_authority_event(self, request: AuthorityEventRequest) -> dict[str, Any]:
        event, created = self.workflow_store.record_authority_event(
            AuthorityChangeEvent(
                source_id=request.source_id,
                idempotency_key=request.idempotency_key,
                authority_id=request.authority_id,
                new_version=request.new_version,
                changed_at=request.changed_at,
                evidence_url=request.evidence_url,
                evidence_sha256=request.evidence_sha256,
            )
        )
        if not created:
            existing_tasks = [
                task.model_dump(mode="json")
                for task in self.workflow_store.list_review_tasks()
                if task.event_id == event.id
            ]
            return {
                "event": event.model_dump(mode="json"),
                "duplicate": True,
                "impact": None,
                "review_tasks": existing_tasks,
            }
        impact = self.register_authority_change(
            event.authority_id,
            AuthorityChangeRequest(new_version=event.new_version, changed_at=event.changed_at.isoformat()),
        )
        review_tasks: list[ReviewTask] = []
        for item_id in impact["stale_item_ids"]:
            item = self._get_item(str(item_id))
            review_tasks.append(
                self.workflow_store.create_review_task(
                    ReviewTask(
                        event_id=event.id,
                        item_id=item.id,
                        priority=_review_priority(item),
                        reason=f"authority {event.authority_id} changed to {event.new_version}",
                    )
                )
            )
        self.audit.append(
            "authority_event_registered",
            {
                "event_id": event.id,
                "source_id": event.source_id,
                "authority_id": event.authority_id,
                "new_version": event.new_version,
                "review_task_ids": [task.id for task in review_tasks],
            },
            occurred_at=event.received_at,
        )
        return {
            "event": event.model_dump(mode="json"),
            "duplicate": False,
            "impact": impact,
            "review_tasks": [task.model_dump(mode="json") for task in review_tasks],
        }

    def review_tasks(
        self,
        *,
        reviewer_id: str | None = None,
        state: ReviewTaskState | None = None,
    ) -> list[ReviewTask]:
        return self.workflow_store.list_review_tasks(reviewer_id=reviewer_id, state=state)

    def assign_review_task(self, task_id: str, request: ReviewTaskAssignmentRequest) -> ReviewTask:
        try:
            task = self.workflow_store.assign(task_id, reviewer_id=request.reviewer_id, assigned_by=request.assigned_by)
        except KeyError as exc:
            raise NotFoundError(f"review task not found: {task_id}") from exc
        self.audit.append(
            "review_task_assigned",
            {"task_id": task.id, "item_id": task.item_id, "reviewer_id": task.reviewer_id, "by": request.assigned_by},
        )
        return task

    def start_review_task(self, task_id: str, request: ReviewTaskStartRequest) -> ReviewTask:
        try:
            task = self.workflow_store.start(task_id, reviewer_id=request.reviewer_id)
        except KeyError as exc:
            raise NotFoundError(f"review task not found: {task_id}") from exc
        self.audit.append("review_task_started", {"task_id": task.id, "by": request.reviewer_id})
        return task

    def resolve_review_task(self, task_id: str, request: ReviewTaskResolutionRequest) -> ReviewTask:
        try:
            task = self.workflow_store.get_review_task(task_id)
        except KeyError as exc:
            raise NotFoundError(f"review task not found: {task_id}") from exc
        if task.reviewer_id != request.reviewer_id:
            raise BadRequestError("only the assigned reviewer can resolve this task")
        self.record_verification(task.item_id, request.verification)
        task = self.workflow_store.resolve(task_id, reviewer_id=request.reviewer_id)
        self.audit.append(
            "review_task_resolved",
            {"task_id": task.id, "item_id": task.item_id, "by": request.reviewer_id},
        )
        return task

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

    def currency_report(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
        scope: ReportScopeKind = "firm",
        practice_area: str | None = None,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> CurrencyMovementReport:
        return currency_movement_report(
            store=self.store,
            graph=self.graph,
            period_start=period_start,
            period_end=period_end,
            scope=scope,
            practice_area=practice_area,
            matter_id=matter_id,
            client_id=client_id,
        )

    def export_currency_report_pack(self, destination: Path, report: CurrencyMovementReport) -> Path:
        pack = self.audit.export_pack(destination)
        report_path = pack.directory / "currency-report.json"
        report_bytes = json.dumps(report.model_dump(mode="json"), sort_keys=True, indent=2).encode("utf-8")
        report_path.write_bytes(report_bytes)
        pdf_path = pack.directory / "currency-report.pdf"
        pdf_bytes = render_currency_report_pdf(report)
        pdf_path.write_bytes(pdf_bytes)
        manifest = json.loads(pack.manifest_path.read_text(encoding="utf-8"))
        manifest.pop("manifest_sha256", None)
        manifest["currency_report_file"] = report_path.name
        manifest["currency_report_sha256"] = hashlib.sha256(report_bytes).hexdigest()
        manifest["currency_report_pdf_file"] = pdf_path.name
        manifest["currency_report_pdf_sha256"] = hashlib.sha256(pdf_bytes).hexdigest()
        manifest_bytes = json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8")
        manifest["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
        pack.manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
        return pack.directory

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


def _review_priority(item: KnowledgeItem) -> ReviewTaskPriority:
    if item.kind in {KnowledgeKind.ADVICE, KnowledgeKind.HOUSE_VIEW}:
        return ReviewTaskPriority.URGENT
    if item.kind is KnowledgeKind.POSITION:
        return ReviewTaskPriority.HIGH
    return ReviewTaskPriority.NORMAL


__all__ = [
    "SolomonService",
    "IngestRequest",
    "DocumentSourceRequest",
    "SourceDocumentIngestRequest",
    "CandidateClaimDeferralRequest",
    "CandidateClaimPromotionRequest",
    "CandidateClaimRejectionRequest",
    "RecallRequest",
    "VerificationRequest",
    "ReviewTaskAssignmentRequest",
    "ReviewTaskResolutionRequest",
    "ReviewTaskStartRequest",
    "VerificationAssignmentRequest",
    "VerificationReviewRequest",
    "AuthorityChangeRequest",
    "AuthorityEventRequest",
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
