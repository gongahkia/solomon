# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
import uuid
from base64 import b64decode
from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlparse

from solomon.api.auth import SOURCE_MANAGE_SCOPE, TENANT_READ_SCOPE, TENANT_WRITE_SCOPE, AuthPrincipal, AuthRole
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
    DependencyAssertionCreateRequest,
    DependencyAssertionDecisionRequest,
    DependencyAssertionWithdrawRequest,
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
from solomon.audit.journal import AuditAttribution, AuditJournal
from solomon.authority_identifiers import SQLiteAuthorityIdentifierStore
from solomon.authority_polling import AuthorityPollBatch, AuthorityPollOutbox, AuthorityPollRetryPolicy
from solomon.authority_sources import (
    AuthorityPollDeadLetter,
    AuthorityPollEventNotFoundError,
    SQLiteAuthoritySourceRegistry,
)
from solomon.boundary.solomon import SolomonBoundary
from solomon.consistency.inspection import ConsistencyInspector
from solomon.consistency.models import ConsistencyReport, ConsistencyScope, RepairPlan, RepairResult
from solomon.consistency.repair import ConsistencyRepairService
from solomon.contracts import AdapterHealth, AuthoritySource, AuthoritySourceAdapter, AuthoritySourceKind
from solomon.credence.policy import CredenceLedger, CredencePolicy
from solomon.currency.cache import CurrencyEvaluationCache
from solomon.currency.contradiction import ContradictionSignal, contradictions_for_item
from solomon.currency.engine import VerificationPolicy, record_verification
from solomon.currency.models import CurrencyState, KnowledgeItem, KnowledgeKind, now_utc
from solomon.currency.prediction import StalenessRiskReport
from solomon.currency.report import (
    CurrencyMovementReport,
    ReportScopeKind,
    currency_movement_report,
    render_currency_report_pdf,
)
from solomon.currency.verification import verification_history
from solomon.errors import BadRequestError, NotFoundError, PolicyRefusalError, SolomonError
from solomon.graph.models import DependencyEdge
from solomon.graph.suggestions import DependencySuggestion, ReferenceExtraction, SuggestionDecision
from solomon.graph.visualization import GraphFormat
from solomon.operations.models import OperationRecord, OperationScope
from solomon.operations.postgres import PostgresOperationStore
from solomon.operations.store import SQLiteOperationStore
from solomon.orchestrator.models import ModelRequest, ModelRouter, RoutedModelResult
from solomon.orchestrator.retrieval import RetrievalEmbeddingProvider, RetrievalOrchestrator
from solomon.retention import ErasureRecord, LegalHoldNotFoundError, LegalHoldRecord, RetentionRegistry, RetentionScope
from solomon.sources.extract import candidate_claims_from_text, extract_document_bytes
from solomon.sources.filesystem import FilesystemDocumentSourceAdapter
from solomon.sources.models import (
    CandidateClaim,
    CandidateClaimStatus,
    DocumentExtractionState,
    DocumentSource,
    DocumentSourceKind,
    SourceDocument,
    SourceSyncRun,
    SourceSyncRunState,
)
from solomon.sources.store import (
    CandidateClaimNotFoundError,
    SourceDocumentNotFoundError,
    SourceNotFoundError,
    SQLiteDocumentStore,
)
from solomon.sources.sync import FilesystemSourceSynchronizer
from solomon.store.encryption import ContentEnvelopeCipher
from solomon.store.factory import create_storage_bundle
from solomon.store.outbox import OutboxRecord
from solomon.store.sqlite import ItemNotFoundError
from solomon.telemetry import SolomonTelemetry
from solomon.workflow.models import AuthorityChangeEvent, ReviewTask, ReviewTaskPriority, ReviewTaskState
from solomon.workflow.store import SQLiteWorkflowStore

ServiceAccess = Literal["read", "write", "curate", "review"]
SERVICE_ACCESS: dict[str, ServiceAccess] = {
    "ingest": "write",
    "register_document_source": "curate",
    "source_documents": "read",
    "document_source_health": "read",
    "document_source_sync_runs": "read",
    "sync_document_source": "curate",
    "retry_source_document_extraction": "curate",
    "ingest_source_document": "curate",
    "candidate_claims": "read",
    "promote_candidate_claim": "curate",
    "reject_candidate_claim": "curate",
    "defer_candidate_claim": "curate",
    "legal_holds": "review",
    "create_legal_hold": "review",
    "release_legal_hold": "review",
    "erasure_requests": "review",
    "erase_retention_scope": "review",
    "apply_retention": "review",
    "recall": "read",
    "answer": "read",
    "complete_model_request": "read",
    "evaluate_currency": "read",
    "record_verification": "review",
    "assign_verification": "review",
    "start_verification_review": "review",
    "verification_queue": "read",
    "detect_contradictions": "read",
    "register_authority_change": "curate",
    "register_authority_source": "curate",
    "schedule_authority_polls": "curate",
    "run_authority_polls": "curate",
    "authority_poll_dead_letters": "read",
    "retry_authority_poll_dead_letter": "curate",
    "register_authority_event": "curate",
    "review_tasks": "read",
    "assign_review_task": "curate",
    "start_review_task": "review",
    "resolve_review_task": "review",
    "contest": "review",
    "affirm": "review",
    "pin": "review",
    "add_dependency": "curate",
    "suggest_dependencies": "curate",
    "dependency_suggestions": "read",
    "confirm_dependency_suggestion": "curate",
    "reject_dependency_suggestion": "curate",
    "defer_dependency_suggestion": "curate",
    "create_dependency_assertion": "curate",
    "dependency_assertions": "read",
    "get_dependency_assertion": "read",
    "dependency_assertion_history": "read",
    "decide_dependency_assertion": "review",
    "withdraw_dependency_assertion": "curate",
    "impact_query": "read",
    "dependency_graph": "read",
    "extract_references": "read",
    "predict_staleness": "read",
    "why": "read",
    "timeline": "read",
    "execute_plan": "write",
    "currency_report": "read",
    "export_currency_report_pack": "read",
    "export_audit_pack": "read",
    "consistency_check": "read",
    "consistency_repair_plan": "review",
    "apply_consistency_repair": "review",
    "operation_status": "read",
}

SERVICE_SPAN_NAMES: dict[str, str] = {
    "ingest": "solomon.ingestion.ingest",
    "register_document_source": "solomon.connector.register",
    "sync_document_source": "solomon.connector.sync",
    "retry_source_document_extraction": "solomon.connector.extract",
    "ingest_source_document": "solomon.connector.ingest_document",
    "recall": "solomon.retrieval.recall",
    "answer": "solomon.retrieval.answer",
    "timeline": "solomon.retrieval.timeline",
    "record_verification": "solomon.review.record_verification",
    "assign_verification": "solomon.review.assign",
    "start_verification_review": "solomon.review.start",
    "resolve_review_task": "solomon.review.resolve",
    "contest": "solomon.review.contest",
    "affirm": "solomon.review.affirm",
    "pin": "solomon.review.pin",
}


@dataclass(frozen=True)
class ServiceAuthorization:
    principal: AuthPrincipal
    correlation_id: str


_service_authorization: ContextVar[ServiceAuthorization | None] = ContextVar("service_authorization", default=None)


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
        tenant_id: str | None = None,
        verification_policy: VerificationPolicy | None = None,
        verification_policy_version: str = "verification-policy.v1",
        credence_policy: CredencePolicy | None = None,
        credence_policy_version: str = "credence-policy.v1",
        embedding_provider: RetrievalEmbeddingProvider | None = None,
        content_cipher: ContentEnvelopeCipher | None = None,
        retention_default_days: int | None = None,
        telemetry: SolomonTelemetry | None = None,
    ) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        journal_dir.mkdir(parents=True, exist_ok=True)
        resolved_database_url = database_url or str(data_dir / "solomon.sqlite3")
        storage = create_storage_bundle(
            resolved_database_url,
            postgres_schema=postgres_schema,
            embedding_provider=embedding_provider,
        )
        self.store = storage.store
        self.graph = storage.graph
        self.index = storage.index
        self.tenant_id = tenant_id
        self.operation_store: Any
        if urlparse(resolved_database_url).scheme in {"postgres", "postgresql"}:
            self.operation_store = PostgresOperationStore(resolved_database_url, schema=postgres_schema)
        else:
            operation_path = getattr(self.store, "path", data_dir / "solomon.sqlite3")
            self.operation_store = SQLiteOperationStore(operation_path)
        self.consistency_signals: Counter[str] = Counter()
        self.telemetry = telemetry or SolomonTelemetry()
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
        self.document_store = SQLiteDocumentStore(data_dir / "sources.sqlite3", content_cipher=content_cipher)
        self.retention_registry = RetentionRegistry(data_dir / "retention" / "registry.json")
        self.retention_default_days = retention_default_days
        self.authority_sources = SQLiteAuthoritySourceRegistry(data_dir / "authority-sources.sqlite3")
        self.authority_identifiers = SQLiteAuthorityIdentifierStore(data_dir / "authority-identifiers.sqlite3")
        self.workflow_store = SQLiteWorkflowStore(data_dir / "workflow.sqlite3")
        self.attestation_key = attestation_key
        self.boundary = boundary or SolomonBoundary(telemetry=self.telemetry)
        self.boundary.set_telemetry(self.telemetry)
        self._ingestion = IngestionService(self)
        self._answer = AnswerService(self)
        self._authority = AuthorityService(self)
        self._recall = RecallService(self)

    def __getattribute__(self, name: str) -> Any:
        value = super().__getattribute__(name)
        access = SERVICE_ACCESS.get(name)
        if access is None or not callable(value):
            return value

        def authorized(*args: Any, **kwargs: Any) -> Any:
            span_name = SERVICE_SPAN_NAMES.get(name, f"solomon.service.{name}")
            with self.telemetry.span(
                span_name,
                attributes={"solomon.service.operation": name, "solomon.service.access": access},
            ):
                self._authorize_service_operation(name, access)
                return value(*args, **kwargs)

        return authorized

    @contextmanager
    def authorized_as(self, principal: AuthPrincipal, correlation_id: str) -> Iterator[None]:
        token = _service_authorization.set(ServiceAuthorization(principal=principal, correlation_id=correlation_id))
        try:
            yield
        finally:
            _service_authorization.reset(token)

    def _authorize_service_operation(self, operation: str, access: ServiceAccess) -> None:
        authorization = _service_authorization.get()
        if authorization is None:
            return
        principal = authorization.principal
        allowed = _service_access_allowed(principal, access)
        self.audit.append(
            "service_authorization",
            {
                "operation": operation,
                "access": access,
                "decision": "allowed" if allowed else "denied",
                "roles": sorted(principal.roles or frozenset({principal.role})),
            },
            attribution=AuditAttribution(actor_id=principal.subject, correlation_id=authorization.correlation_id),
        )
        if not allowed:
            raise PolicyRefusalError(
                "principal is not authorized for service operation",
                details={"operation": operation},
            )

    def _audit_content_encryption(
        self,
        *,
        source_id: str,
        document_id: str | None = None,
        candidate_count: int = 0,
        document_count: int = 1,
    ) -> None:
        cipher = self.document_store.content_cipher
        if cipher is None:
            return
        authorization = _service_authorization.get()
        actor_id = authorization.principal.subject if authorization is not None else "system:content-encryption"
        correlation_id = (
            authorization.correlation_id if authorization is not None else f"content-encryption:{source_id}"
        )
        self.audit.append(
            "content_envelope_encryption",
            {
                "decision": "allowed",
                "protection": "envelope-encrypted",
                "key_ref": cipher.key_ref,
                "source_id": source_id,
                "document_id": document_id,
                "document_count": document_count,
                "candidate_count": candidate_count,
            },
            attribution=AuditAttribution(actor_id=actor_id, correlation_id=correlation_id),
        )

    def _audit_retention(self, event_type: str, payload: dict[str, Any]) -> AuditAttribution:
        authorization = _service_authorization.get()
        actor_id = authorization.principal.subject if authorization is not None else "system:retention"
        correlation_id = authorization.correlation_id if authorization is not None else f"retention:{uuid.uuid4().hex}"
        attribution = AuditAttribution(actor_id=actor_id, correlation_id=correlation_id)
        self.audit.append(event_type, payload, attribution=attribution)
        return attribution

    def legal_holds(self, *, active_only: bool = False) -> list[LegalHoldRecord]:
        return self.retention_registry.list_holds(active_only=active_only)

    def create_legal_hold(self, *, scope: RetentionScope, scope_id: str, reason: str) -> LegalHoldRecord:
        hold = self.retention_registry.create_hold(scope=scope, scope_id=scope_id, reason=reason)
        self._audit_retention(
            "legal_hold_created",
            {
                "decision": "allowed",
                "hold_id": hold.hold_id,
                "scope": hold.scope,
                "scope_id_sha256": digest(hold.scope_id),
                "reason_sha256": digest(hold.reason),
            },
        )
        return hold

    def release_legal_hold(self, hold_id: str) -> LegalHoldRecord:
        try:
            hold = self.retention_registry.release_hold(hold_id)
        except LegalHoldNotFoundError as exc:
            raise NotFoundError("legal hold not found") from exc
        self._audit_retention(
            "legal_hold_released",
            {"decision": "allowed", "hold_id": hold.hold_id, "scope": hold.scope},
        )
        return hold

    def erasure_requests(self) -> list[ErasureRecord]:
        return self.retention_registry.list_erasures()

    def erase_retention_scope(
        self,
        *,
        scope: RetentionScope,
        scope_id: str,
        subject_ref: str,
        lawful_basis: str,
    ) -> ErasureRecord:
        return self._erase_retention_scope(
            scope=scope,
            scope_id=scope_id,
            subject_ref=subject_ref,
            lawful_basis=lawful_basis,
        )

    def apply_retention(self, *, as_of: datetime | None = None) -> list[ErasureRecord]:
        if self.retention_default_days is None:
            raise BadRequestError("retention policy is not configured")
        cutoff = (as_of or now_utc()).timestamp() - self.retention_default_days * 86_400
        records: list[ErasureRecord] = []
        for item in self.store.get_many():
            if item.ingested_at.timestamp() > cutoff or _is_erased_for_retention(item):
                continue
            records.append(
                self._erase_retention_scope(
                    scope="item",
                    scope_id=item.id,
                    subject_ref=f"retention:{item.id}",
                    lawful_basis="configured-retention",
                )
            )
        self._audit_retention(
            "retention_policy_applied",
            {
                "decision": "allowed",
                "retention_default_days": self.retention_default_days,
                "erased_count": sum(record.state == "erased" for record in records),
                "held_count": sum(record.state == "held" for record in records),
            },
        )
        return records

    def _erase_retention_scope(
        self,
        *,
        scope: RetentionScope,
        scope_id: str,
        subject_ref: str,
        lawful_basis: str,
    ) -> ErasureRecord:
        items = _retention_scope_items(self.store.get_many(), scope=scope, scope_id=scope_id)
        holds = self.retention_registry.matching_holds(items)
        if holds:
            record = self.retention_registry.record_erasure(
                scope=scope,
                scope_id=scope_id,
                subject_ref=subject_ref,
                lawful_basis=lawful_basis,
                state="held",
                affected_item_ids=[item.id for item in items],
                legal_hold_ids=[hold.hold_id for hold in holds],
            )
            self._audit_retention(
                "erasure_blocked_by_legal_hold",
                {
                    "decision": "denied",
                    "request_id": record.request_id,
                    "scope": scope,
                    "scope_id_sha256": digest(scope_id),
                    "affected_item_count": len(items),
                    "legal_hold_count": len(holds),
                },
            )
            return record
        erased_items = [item for item in items if not _is_erased_for_retention(item)]
        now = now_utc()
        for item in erased_items:
            metadata = dict(item.metadata)
            metadata["retention"] = {
                "state": "erased",
                "subject_ref_sha256": hashlib.sha256(subject_ref.encode("utf-8")).hexdigest(),
                "lawful_basis": lawful_basis,
                "erased_at": now.isoformat(),
            }
            erased = item.model_copy(
                update={
                    "content": "[erased under retention policy]",
                    "currency_state": CurrencyState.RETIRED,
                    "metadata": metadata,
                }
            )
            self.store.update_item(erased, event_type="knowledge_item_erased", occurred_at=now)
            self.index.upsert_item(erased)
        record = self.retention_registry.record_erasure(
            scope=scope,
            scope_id=scope_id,
            subject_ref=subject_ref,
            lawful_basis=lawful_basis,
            state="erased",
            affected_item_ids=[item.id for item in erased_items],
        )
        attribution = self._audit_retention(
            "erasure_completed",
            {
                "decision": "allowed",
                "request_id": record.request_id,
                "scope": scope,
                "scope_id_sha256": digest(scope_id),
                "affected_item_count": len(erased_items),
                "subject_ref_sha256": record.subject_ref_sha256,
            },
        )
        self.audit.record_erasure_tombstone(
            subject_ref=subject_ref,
            lawful_basis=lawful_basis,
            by=attribution.actor_id or "system:retention",
            attribution=attribution,
            request_id=record.request_id,
            affected_item_count=len(erased_items),
        )
        return record

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

    def document_source_health(self, source_id: str) -> AdapterHealth:
        source = self.document_store.get_source(source_id)
        if source.kind is DocumentSourceKind.FILESYSTEM:
            return FilesystemDocumentSourceAdapter().health(source)
        return AdapterHealth(healthy=False, detail=f"health check unavailable for {source.kind.value} source")

    def document_source_sync_runs(self, source_id: str) -> list[SourceSyncRun]:
        return self.document_store.list_sync_runs(source_id)

    def sync_document_source(self, source_id: str) -> SourceSyncRun:
        try:
            source = self.document_store.get_source(source_id)
        except SourceNotFoundError as exc:
            raise NotFoundError(f"document source not found: {source_id}") from exc
        run = self.document_store.write_sync_run(SourceSyncRun(source_id=source_id))
        try:
            if source.kind is not DocumentSourceKind.FILESYSTEM:
                raise BadRequestError(f"synchronization unavailable for {source.kind.value} source")
            result = FilesystemSourceSynchronizer(self.document_store).sync(source_id)
        except (OSError, ValueError, SolomonError) as exc:
            failed = run.model_copy(
                update={
                    "state": SourceSyncRunState.FAILED,
                    "completed_at": now_utc(),
                    "error": f"{exc.__class__.__name__}: {str(exc)[:400]}",
                }
            )
            self.document_store.write_sync_run(failed)
            self.audit.append("document_source_sync_failed", {"source_id": source_id, "run_id": run.id})
            if isinstance(exc, SolomonError):
                raise
            raise BadRequestError(str(exc)) from exc
        completed = run.model_copy(
            update={
                "state": SourceSyncRunState.SUCCEEDED,
                "completed_at": now_utc(),
                "discovered": result.discovered,
                "created": result.created,
                "updated": result.updated,
                "unchanged": result.unchanged,
                "deleted": result.deleted,
                "checkpoint": result.checkpoint.model_dump(mode="json"),
            }
        )
        self.document_store.write_sync_run(completed)
        if completed.created or completed.updated:
            self._audit_content_encryption(
                source_id=source_id,
                candidate_count=0,
                document_count=completed.created + completed.updated,
            )
        self.audit.append(
            "document_source_synced",
            {
                "source_id": source_id,
                "run_id": completed.id,
                "created": completed.created,
                "updated": completed.updated,
                "deleted": completed.deleted,
            },
        )
        return completed

    def retry_source_document_extraction(self, source_id: str, document_id: str) -> SourceDocument:
        try:
            document = FilesystemSourceSynchronizer(self.document_store).retry_extraction(source_id, document_id)
        except (SourceNotFoundError, SourceDocumentNotFoundError) as exc:
            raise NotFoundError(str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise BadRequestError(str(exc)) from exc
        if document.extraction_state is DocumentExtractionState.READY and not self.document_store.list_candidates(
            document.id
        ):
            candidates: list[CandidateClaim] = []
            for content, start, end in candidate_claims_from_text(document.content):
                candidates.append(
                    self.document_store.add_candidate(
                        CandidateClaim(document_id=document.id, content=content, start_offset=start, end_offset=end)
                    )
                )
        else:
            candidates = []
        self._audit_content_encryption(
            source_id=source_id,
            document_id=document.id,
            candidate_count=len(candidates),
        )
        self.audit.append(
            "source_document_extraction_retried",
            {
                "source_id": source_id,
                "document_id": document.id,
                "extraction_state": document.extraction_state.value,
            },
        )
        return document

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
        self._audit_content_encryption(
            source_id=source_id,
            document_id=document.id,
            candidate_count=len(candidates),
        )
        self._authority.record_source_document_ingestion(document, candidate_count=len(candidates))
        self._authority.mark_dependency_assertions_for_source_revision(
            previous_document_id=document.previous_version_id,
            replacement_document_id=document.id,
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
                source_document_id=document.id,
                source_document_version=document.version,
                previous_source_document_id=document.previous_version_id,
                source_document_span_start=candidate.start_offset,
                source_document_span_end=candidate.end_offset,
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

    def register_authority_source(self, source: AuthoritySource) -> AuthoritySource:
        return self.authority_sources.register(source)

    def schedule_authority_polls(self, *, as_of: datetime | None = None) -> list[str]:
        return AuthorityPollOutbox(
            registry=self.authority_sources,
            adapters={},
            consume_event=self._register_polled_authority_event,
        ).schedule_due(as_of=as_of)

    def run_authority_polls(
        self,
        adapters: Mapping[AuthoritySourceKind, AuthoritySourceAdapter],
        *,
        as_of: datetime | None = None,
        limit: int = 100,
        retry_policy: AuthorityPollRetryPolicy | None = None,
    ) -> AuthorityPollBatch:
        return AuthorityPollOutbox(
            registry=self.authority_sources,
            adapters=adapters,
            consume_event=self._register_polled_authority_event,
            retry_policy=retry_policy,
        ).run_due(as_of=as_of, limit=limit)

    def authority_poll_dead_letters(self, *, limit: int = 100) -> list[AuthorityPollDeadLetter]:
        try:
            return self.authority_sources.dead_letter_poll_events(limit=limit)
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def retry_authority_poll_dead_letter(self, event_id: str, *, as_of: datetime | None = None) -> OutboxRecord:
        try:
            return self.authority_sources.requeue_dead_letter(event_id, available_at=as_of)
        except AuthorityPollEventNotFoundError as exc:
            raise NotFoundError(f"authority poll event not found: {event_id}") from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def register_authority_event(self, request: AuthorityEventRequest) -> dict[str, Any]:
        return self._register_polled_authority_event(
            AuthorityChangeEvent(
                source_id=request.source_id,
                idempotency_key=request.idempotency_key,
                authority_id=request.authority_id,
                previous_version=request.previous_version,
                new_version=request.new_version,
                changed_at=request.changed_at,
                evidence_url=request.evidence_url,
                evidence_sha256=request.evidence_sha256,
                diff=request.diff,
            )
        )

    def _register_polled_authority_event(self, authority_event: AuthorityChangeEvent) -> dict[str, Any]:
        event, created = self.workflow_store.record_authority_event(authority_event)
        if not created and self.workflow_store.authority_event_processed(event.id):
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
        try:
            impact = self._authority.register_authority_change(
                event.authority_id,
                AuthorityChangeRequest(new_version=event.new_version, changed_at=event.changed_at.isoformat()),
                change_id=event.id,
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
            if not any(
                entry.event_type == "authority_event_registered" and entry.payload.get("event_id") == event.id
                for entry in self.audit.list_entries()
            ):
                self.audit.append(
                    "authority_event_registered",
                    {
                        "event_id": event.id,
                        "source_id": event.source_id,
                        "authority_id": event.authority_id,
                        "new_version": event.new_version,
                        "affected_item_ids": impact["stale_item_ids"],
                        "review_task_ids": [task.id for task in review_tasks],
                        "reason": "authority change flagged for human review",
                        "decision": "flag_for_review",
                    },
                    occurred_at=event.received_at,
                    attribution=AuditAttribution(
                        actor_id="system:authority-monitor",
                        correlation_id=f"authority_event:{event.id}",
                    ),
                )
            self.workflow_store.mark_authority_event_processed(event.id)
        except Exception as exc:
            self.workflow_store.mark_authority_event_failed(event.id, error=exc)
            raise
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
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> list[DependencySuggestion]:
        return self._authority.dependency_suggestions(
            item_id=item_id,
            decision=decision,
            limit=limit,
            matter_id=matter_id,
            client_id=client_id,
        )

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

    def defer_dependency_suggestion(
        self,
        suggestion_id: str,
        request: DependencySuggestionDecisionRequest,
    ) -> DependencySuggestion:
        return self._authority.defer_dependency_suggestion(suggestion_id, request)

    def create_dependency_assertion(self, request: DependencyAssertionCreateRequest) -> DependencySuggestion:
        return self._authority.create_dependency_assertion(request)

    def dependency_assertions(self, **filters: Any) -> list[DependencySuggestion]:
        return self._authority.dependency_assertions(**filters)

    def get_dependency_assertion(
        self,
        assertion_id: str,
        *,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> DependencySuggestion:
        return self._authority.get_dependency_assertion(assertion_id, matter_id=matter_id, client_id=client_id)

    def decide_dependency_assertion(
        self,
        assertion_id: str,
        request: DependencyAssertionDecisionRequest,
    ) -> DependencySuggestion | DependencyEdge:
        return self._authority.decide_dependency_assertion(assertion_id, request)

    def withdraw_dependency_assertion(
        self,
        assertion_id: str,
        request: DependencyAssertionWithdrawRequest,
    ) -> DependencySuggestion:
        return self._authority.withdraw_dependency_assertion(assertion_id, request)

    def dependency_assertion_history(
        self,
        assertion_id: str,
        *,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        return self._authority.dependency_assertion_history(assertion_id, matter_id=matter_id, client_id=client_id)

    def impact_query(self, authority_id: str, *, as_of: datetime | None = None) -> dict[str, Any]:
        return self._authority.impact_query(authority_id, as_of=as_of)

    def consistency_check(
        self,
        *,
        matter_id: str,
        client_id: str,
        stuck_after_seconds: int = 900,
    ) -> ConsistencyReport:
        report = ConsistencyInspector(self).check(
            ConsistencyScope(tenant_id=self.tenant_id, matter_id=matter_id, client_id=client_id),
            stuck_after=timedelta(seconds=stuck_after_seconds),
        )
        self.consistency_signals["checks"] += 1
        self.consistency_signals["findings"] += len(report.findings)
        return report

    def consistency_repair_plan(self, *, matter_id: str, client_id: str) -> RepairPlan:
        plan = ConsistencyRepairService(self).plan(
            ConsistencyScope(tenant_id=self.tenant_id, matter_id=matter_id, client_id=client_id)
        )
        self.consistency_signals["repairs_planned"] += len(plan.actions)
        return plan

    def apply_consistency_repair(self, plan: RepairPlan) -> RepairResult:
        result = ConsistencyRepairService(self).apply(plan)
        self.consistency_signals["repairs_applied" if result.applied else "repairs_refused"] += 1
        return result

    def operation_status(self, *, matter_id: str, client_id: str) -> list[OperationRecord]:
        return cast(
            list[OperationRecord],
            self.operation_store.list(
                scope=OperationScope(tenant_id=self.tenant_id, matter_id=matter_id, client_id=client_id),
                limit=10_000,
            ),
        )

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
        assertions = {
            assertion.id: {
                "assertion": assertion.model_dump(mode="json"),
                "events": self.graph.list_dependency_suggestion_events(assertion.id),
            }
            for assertion in self._authority.dependency_assertions(limit=10_000)
        }
        assertions_path = pack.directory / "dependency-assertions.json"
        assertions_bytes = json.dumps(assertions, sort_keys=True, indent=2).encode("utf-8")
        assertions_path.write_bytes(assertions_bytes)
        manifest = json.loads(pack.manifest_path.read_text(encoding="utf-8"))
        manifest.pop("manifest_sha256", None)
        manifest["verification_history_file"] = history_path.name
        manifest["verification_history_sha256"] = hashlib.sha256(history_bytes).hexdigest()
        manifest["contradictions_file"] = contradictions_path.name
        manifest["contradictions_sha256"] = hashlib.sha256(contradictions_bytes).hexdigest()
        manifest["dependency_assertions_file"] = assertions_path.name
        manifest["dependency_assertions_sha256"] = hashlib.sha256(assertions_bytes).hexdigest()
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

    def schedule_dependency_suggestions(self, item: KnowledgeItem) -> OperationRecord:
        return self._authority.record_suggestion_generation(item)

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


def _service_access_allowed(principal: AuthPrincipal, access: ServiceAccess) -> bool:
    if access == "read":
        return principal.has_scope(TENANT_READ_SCOPE)
    if access == "write":
        return principal.has_scope(TENANT_WRITE_SCOPE)
    if access == "curate":
        return principal.has_scope(SOURCE_MANAGE_SCOPE)
    review_roles: tuple[AuthRole, ...] = ("admin", "reviewer", "lawyer")
    return any(principal.has_role(role) for role in review_roles)


def _retention_scope_items(
    items: list[KnowledgeItem],
    *,
    scope: RetentionScope,
    scope_id: str,
) -> list[KnowledgeItem]:
    if scope == "item":
        return [item for item in items if item.id == scope_id]
    if scope == "matter":
        return [item for item in items if item.matter_id == scope_id]
    return [item for item in items if item.client_id == scope_id]


def _is_erased_for_retention(item: KnowledgeItem) -> bool:
    retention = item.metadata.get("retention")
    return isinstance(retention, dict) and retention.get("state") == "erased"


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
    "DependencyAssertionCreateRequest",
    "DependencyAssertionDecisionRequest",
    "DependencyAssertionWithdrawRequest",
    "AnswerRequest",
    "AnswerResponse",
    "WhyTrace",
    "PrimitivePlanStep",
    "PrimitivePlanRequest",
    "PrimitiveStepResult",
    "PrimitivePlanExecution",
    "record_verification",
]
