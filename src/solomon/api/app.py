# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from solomon import __version__
from solomon.api.auth import (
    ADMIN_AUTH_SCOPES,
    AuthPrincipal,
    extract_api_key,
    mapped_oidc_roles,
    primary_role,
    required_scope_for_request,
    scopes_for_roles,
    static_secret_matches,
    validate_auth_scopes,
)
from solomon.api.oidc import OIDCIdentity, OIDCValidationError, OIDCValidator
from solomon.api.report_routes import register_currency_report_routes
from solomon.api.service import (
    AffirmRequest,
    AnswerRequest,
    AuthorityChangeRequest,
    AuthorityEventRequest,
    CandidateClaimDeferralRequest,
    CandidateClaimPromotionRequest,
    CandidateClaimRejectionRequest,
    ContestRequest,
    DependencyRequest,
    DependencySuggestionDecisionRequest,
    DependencySuggestionRequest,
    DocumentSourceRequest,
    IngestRequest,
    PinRequest,
    PrimitivePlanRequest,
    RecallRequest,
    ReferenceExtractionRequest,
    ReviewTaskAssignmentRequest,
    ReviewTaskResolutionRequest,
    ReviewTaskStartRequest,
    SolomonService,
    SourceDocumentIngestRequest,
    StalenessPredictionRequest,
    VerificationRequest,
)
from solomon.api.service_principals import (
    ServicePrincipalAlreadyExistsError,
    ServicePrincipalNotFoundError,
    ServicePrincipalRecord,
    ServicePrincipalRegistry,
)
from solomon.api.tenancy import (
    TenantAlreadyExistsError,
    TenantNotFoundError,
    TenantRecord,
    TenantRegistry,
    is_valid_tenant_id,
)
from solomon.audit.journal import AuditAttribution
from solomon.boundary.solomon import BoundaryImportStatus, SolomonBoundary, probe_boundary_client
from solomon.config import (
    Settings,
    boundary_policy_from_settings,
    credence_policy_from_settings,
    embedding_provider_from_settings,
    get_settings,
    verification_policy_from_settings,
)
from solomon.errors import SolomonError
from solomon.graph.suggestions import SuggestionDecision
from solomon.graph.visualization import GraphFormat
from solomon.observability import SolomonMetrics, request_started
from solomon.orchestrator.models import (
    LocalModelEndpoint,
    ModelEndpoint,
    ModelRouter,
    OpenAIResponsesEndpoint,
    RemoteZDREndpoint,
    RoutingPolicy,
)
from solomon.workflow.models import ReviewTaskState

PUBLIC_PATHS = {"/health", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json"}
TENANT_MANAGEMENT_PREFIX = "/tenants"
DEFAULT_DATABASE_URL = str(Settings.model_fields["database_url"].default)


class HealthResponse(BaseModel):
    status: str = Field(..., examples=["ok"])
    service: str = "solomon"
    version: str = __version__


class ReadyResponse(BaseModel):
    ready: bool
    boundary_client_importable: bool


class DiagnosticsResponse(BaseModel):
    service: str = "solomon"
    version: str = __version__
    boundary: BoundaryImportStatus
    settings: dict[str, Any]


class TenantCreateRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant-a"])
    display_name: str | None = Field(default=None, max_length=120)
    api_key: str | None = Field(default=None, min_length=8)
    api_key_scopes: list[str] | None = Field(default=None, examples=[["tenant:read", "tenant:write"]])


class TenantResponse(BaseModel):
    tenant_id: str
    display_name: str | None
    status: str
    created_at: str
    updated_at: str
    api_key_configured: bool
    api_key_scopes: list[str]


class ServicePrincipalCreateRequest(BaseModel):
    principal_id: str = Field(..., examples=["document-connector"])
    tenant_id: str = Field(..., examples=["tenant-a"])
    scopes: list[str] = Field(default_factory=lambda: ["tenant:read"])


class ServicePrincipalResponse(BaseModel):
    principal_id: str
    tenant_id: str
    status: str
    created_at: str
    updated_at: str
    scopes: list[str]


class ServicePrincipalCredentialResponse(ServicePrincipalResponse):
    credential: str


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    tenant_registry = TenantRegistry(resolved_settings.data_dir / "tenants" / "registry.json")
    service_principal_registry = ServicePrincipalRegistry(
        resolved_settings.data_dir / "service-principals" / "registry.json"
    )
    vp = verification_policy_from_settings(resolved_settings)
    cp = credence_policy_from_settings(resolved_settings)
    embedding_provider = embedding_provider_from_settings(resolved_settings)
    service = SolomonService(
        data_dir=resolved_settings.data_dir,
        journal_dir=resolved_settings.journal_dir,
        attestation_key=resolved_settings.verification_attestation_key,
        database_url=_service_database_url(resolved_settings, resolved_settings.data_dir),
        verification_policy=vp, verification_policy_version=resolved_settings.verification_policy_version,
        credence_policy=cp, credence_policy_version=resolved_settings.credence_policy_version,
        embedding_provider=embedding_provider,
        boundary=SolomonBoundary(policy=boundary_policy_from_settings(resolved_settings)),
    )
    tenant_services: dict[str, SolomonService] = {}
    metrics = SolomonMetrics()
    metrics.attach(service)

    def service_for_tenant(tenant_id: str) -> SolomonService:
        existing = tenant_services.get(tenant_id)
        if existing is not None:
            return existing
        tenant_service = SolomonService(
            data_dir=resolved_settings.data_dir / "tenants" / tenant_id,
            journal_dir=resolved_settings.journal_dir / "tenants" / tenant_id,
            attestation_key=resolved_settings.verification_attestation_key,
            database_url=_service_database_url(resolved_settings, resolved_settings.data_dir / "tenants" / tenant_id),
            postgres_schema=_postgres_schema_for_tenant(resolved_settings, tenant_id),
            verification_policy=vp, verification_policy_version=resolved_settings.verification_policy_version,
            credence_policy=cp, credence_policy_version=resolved_settings.credence_policy_version,
            embedding_provider=embedding_provider,
            boundary=SolomonBoundary(policy=boundary_policy_from_settings(resolved_settings)),
        )
        metrics.attach(tenant_service)
        tenant_services[tenant_id] = tenant_service
        return tenant_service

    def active_service(request: Request) -> SolomonService:
        resolved = getattr(request.state, "service", None)
        if isinstance(resolved, SolomonService):
            return resolved
        return service

    app = FastAPI(
        title="Solomon",
        version=__version__,
        summary="Good-law engine for firm knowledge behind the Solomon boundary.",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.settings = resolved_settings
    app.state.service = service
    app.state.router = _model_router_from_settings(resolved_settings)
    app.state.tenant_registry = tenant_registry
    app.state.service_principal_registry = service_principal_registry
    app.state.metrics = metrics
    app.state.oidc_validator = _oidc_validator_from_settings(resolved_settings)

    def active_router() -> ModelRouter:
        resolved = getattr(app.state, "router", None)
        if isinstance(resolved, ModelRouter):
            return resolved
        return _model_router_from_settings(resolved_settings)

    @app.middleware("http")
    async def server_api_key_middleware(request: Request, call_next: Any) -> Any:
        request.state.tenant_id = "local"
        request.state.service = service
        request.state.principal = AuthPrincipal(
            subject="local",
            role="admin",
            tenant_id=None,
            scopes=ADMIN_AUTH_SCOPES,
        )
        path = request.url.path
        if resolved_settings.sku == "server" and path not in PUBLIC_PATHS:
            supplied_api_key = extract_api_key(request.headers)
            required_scope = required_scope_for_request(request.method, path)
            request.state.correlation_id = _correlation_id(request)
            if _is_admin_path(path):
                principal = _admin_principal(resolved_settings, supplied_api_key)
                if principal is None:
                    principal = _oidc_principal_for_request(
                        request,
                        app.state.oidc_validator,
                        resolved_settings,
                        service,
                        tenant_id=None,
                        required_scope=required_scope,
                    )
                if principal is None:
                    return _auth_error()
                if not principal.has_scope(required_scope):
                    return _forbidden_error(required_scope)
                request.state.principal = principal
                with service.authorized_as(principal, request.state.correlation_id):
                    return await call_next(request)

            tenant_id = request.headers.get("x-tenant-id")
            if tenant_id is None or not is_valid_tenant_id(tenant_id):
                return JSONResponse(
                    status_code=400,
                    content={"error": {"code": "invalid_tenant", "message": "valid x-tenant-id header required"}},
                )
            record = tenant_registry.get(tenant_id)
            if record is None:
                if not resolved_settings.server_auto_provision_tenants:
                    return JSONResponse(
                        status_code=404,
                        content={"error": {"code": "tenant_not_found", "message": "tenant is not registered"}},
                    )
                if _admin_principal(resolved_settings, supplied_api_key) is None:
                    return _auth_error()
                record = tenant_registry.ensure_tenant(tenant_id)
            if record.status != "active":
                return JSONResponse(
                    status_code=403,
                    content={"error": {"code": "tenant_suspended", "message": "tenant is suspended"}},
                )
            service_principal = _service_principal(service_principal_registry, tenant_id, request)
            principal = service_principal or _tenant_principal(
                resolved_settings, tenant_registry, record, tenant_id, supplied_api_key
            )
            if principal is None:
                principal = _oidc_principal_for_request(
                    request,
                    app.state.oidc_validator,
                    resolved_settings,
                    service,
                    tenant_id=tenant_id,
                    required_scope=required_scope,
                )
            if principal is None:
                if _service_principal_credential(request) is not None:
                    _record_service_principal_decision(service, None, tenant_id, request.state.correlation_id, "denied")
                return _auth_error()
            if not principal.has_scope(required_scope):
                if service_principal is not None:
                    _record_service_principal_decision(
                        service, service_principal, tenant_id, request.state.correlation_id, "denied"
                    )
                return _forbidden_error(required_scope)
            if service_principal is not None:
                _record_service_principal_decision(
                    service, service_principal, tenant_id, request.state.correlation_id, "allowed"
                )
            request.state.tenant_id = tenant_id
            request.state.service = service_for_tenant(tenant_id)
            request.state.principal = principal
            with request.state.service.authorized_as(principal, request.state.correlation_id):
                return await call_next(request)
        return await call_next(request)

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next: Any) -> Any:
        started_at = request_started()
        try:
            response = await call_next(request)
        except Exception:
            if request.url.path != "/metrics":
                metrics.observe_http(
                    method=request.method,
                    path=request.url.path,
                    status=500,
                    elapsed_seconds=request_started() - started_at,
                )
            raise
        if request.url.path != "/metrics":
            metrics.observe_http(
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                elapsed_seconds=request_started() - started_at,
            )
        return response

    @app.exception_handler(SolomonError)
    def solomon_error_handler(_request: Request, exc: SolomonError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.error_payload()})

    @app.exception_handler(RequestValidationError)
    def request_validation_error_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "category": "validation",
                    "code": "validation_failed",
                    "message": "request validation failed",
                    "retryable": False,
                    "details": {},
                }
            },
        )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/ready", response_model=ReadyResponse)
    def ready() -> ReadyResponse:
        boundary = probe_boundary_client(resolved_settings.boundary_engine_path)
        return ReadyResponse(ready=boundary.importable, boundary_client_importable=boundary.importable)

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> Response:
        payload, content_type = metrics.render([service, *tenant_services.values()])
        return Response(content=payload, media_type=content_type)

    @app.get("/diagnostics", response_model=DiagnosticsResponse)
    def diagnostics() -> DiagnosticsResponse:
        return DiagnosticsResponse(
            boundary=probe_boundary_client(resolved_settings.boundary_engine_path),
            settings=resolved_settings.public_diagnostics(),
        )

    @app.get("/tenants", response_model=list[TenantResponse])
    def tenants() -> list[TenantResponse]:
        return [_tenant_response(record) for record in tenant_registry.list_tenants()]

    @app.post("/tenants", response_model=TenantResponse, status_code=201)
    def create_tenant(payload: TenantCreateRequest) -> TenantResponse:
        if not is_valid_tenant_id(payload.tenant_id):
            raise HTTPException(status_code=400, detail="invalid tenant_id")
        try:
            api_key_scopes = (
                validate_auth_scopes(payload.api_key_scopes) if payload.api_key_scopes is not None else None
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            record = tenant_registry.create_tenant(
                payload.tenant_id,
                display_name=payload.display_name,
                api_key=payload.api_key,
                api_key_scopes=api_key_scopes,
            )
        except TenantAlreadyExistsError as exc:
            raise HTTPException(status_code=409, detail="tenant already exists") from exc
        return _tenant_response(record)

    @app.post("/tenants/{tenant_id}/suspend", response_model=TenantResponse)
    def suspend_tenant(tenant_id: str) -> TenantResponse:
        if not is_valid_tenant_id(tenant_id):
            raise HTTPException(status_code=400, detail="invalid tenant_id")
        try:
            return _tenant_response(tenant_registry.suspend_tenant(tenant_id))
        except TenantNotFoundError as exc:
            raise HTTPException(status_code=404, detail="tenant not found") from exc

    @app.post("/tenants/{tenant_id}/reactivate", response_model=TenantResponse)
    def reactivate_tenant(tenant_id: str) -> TenantResponse:
        if not is_valid_tenant_id(tenant_id):
            raise HTTPException(status_code=400, detail="invalid tenant_id")
        try:
            return _tenant_response(tenant_registry.reactivate_tenant(tenant_id))
        except TenantNotFoundError as exc:
            raise HTTPException(status_code=404, detail="tenant not found") from exc

    @app.get("/service-principals", response_model=list[ServicePrincipalResponse])
    def service_principals(tenant_id: str | None = None) -> list[ServicePrincipalResponse]:
        records = service_principal_registry.list_principals(tenant_id=tenant_id)
        return [_service_principal_response(record) for record in records]

    @app.post("/service-principals", response_model=ServicePrincipalCredentialResponse, status_code=201)
    def create_service_principal(
        request: Request,
        payload: ServicePrincipalCreateRequest,
    ) -> ServicePrincipalCredentialResponse:
        tenant = tenant_registry.get(payload.tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="tenant not found")
        if tenant.status != "active":
            raise HTTPException(status_code=403, detail="tenant is suspended")
        try:
            record, credential = service_principal_registry.create(
                principal_id=payload.principal_id,
                tenant_id=payload.tenant_id,
                scopes=validate_auth_scopes(payload.scopes),
            )
        except ServicePrincipalAlreadyExistsError as exc:
            raise HTTPException(status_code=409, detail="service principal already exists") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _record_service_principal_lifecycle(service, request, "created", record)
        response = _service_principal_response(record).model_dump()
        return ServicePrincipalCredentialResponse(**response, credential=credential)

    @app.post("/service-principals/{principal_id}/rotate", response_model=ServicePrincipalCredentialResponse)
    def rotate_service_principal(request: Request, principal_id: str) -> ServicePrincipalCredentialResponse:
        try:
            record, credential = service_principal_registry.rotate(principal_id)
        except ServicePrincipalNotFoundError as exc:
            raise HTTPException(status_code=404, detail="service principal not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _record_service_principal_lifecycle(service, request, "rotated", record)
        response = _service_principal_response(record).model_dump()
        return ServicePrincipalCredentialResponse(**response, credential=credential)

    @app.post("/service-principals/{principal_id}/revoke", response_model=ServicePrincipalResponse)
    def revoke_service_principal(request: Request, principal_id: str) -> ServicePrincipalResponse:
        try:
            record = service_principal_registry.revoke(principal_id)
        except ServicePrincipalNotFoundError as exc:
            raise HTTPException(status_code=404, detail="service principal not found") from exc
        _record_service_principal_lifecycle(service, request, "revoked", record)
        return _service_principal_response(record)

    @app.post("/ingest")
    def ingest(request: Request, payload: IngestRequest) -> dict[str, Any]:
        return active_service(request).ingest(payload).model_dump(mode="json")

    @app.post("/sources")
    def register_document_source(request: Request, payload: DocumentSourceRequest) -> dict[str, Any]:
        return active_service(request).register_document_source(payload).model_dump(mode="json")

    @app.get("/sources/{source_id}/documents")
    def source_documents(request: Request, source_id: str) -> list[dict[str, Any]]:
        return [document.model_dump(mode="json") for document in active_service(request).source_documents(source_id)]

    @app.post("/sources/{source_id}/documents")
    def ingest_source_document(
        request: Request,
        source_id: str,
        payload: SourceDocumentIngestRequest,
    ) -> dict[str, Any]:
        document, candidates = active_service(request).ingest_source_document(source_id, payload)
        return {
            "document": document.model_dump(mode="json"),
            "candidate_claims": [candidate.model_dump(mode="json") for candidate in candidates],
        }

    @app.get("/source-documents/{document_id}/candidates")
    def candidate_claims(request: Request, document_id: str) -> list[dict[str, Any]]:
        candidates = active_service(request).candidate_claims(document_id)
        return [candidate.model_dump(mode="json") for candidate in candidates]

    @app.post("/candidate-claims/{candidate_id}/promote")
    def promote_candidate_claim(
        request: Request,
        candidate_id: str,
        payload: CandidateClaimPromotionRequest,
    ) -> dict[str, Any]:
        return active_service(request).promote_candidate_claim(candidate_id, payload).model_dump(mode="json")

    @app.post("/candidate-claims/{candidate_id}/reject")
    def reject_candidate_claim(
        request: Request,
        candidate_id: str,
        payload: CandidateClaimRejectionRequest,
    ) -> dict[str, Any]:
        return active_service(request).reject_candidate_claim(candidate_id, payload).model_dump(mode="json")

    @app.post("/candidate-claims/{candidate_id}/defer")
    def defer_candidate_claim(
        request: Request,
        candidate_id: str,
        payload: CandidateClaimDeferralRequest,
    ) -> dict[str, Any]:
        return active_service(request).defer_candidate_claim(candidate_id, payload).model_dump(mode="json")

    @app.post("/recall")
    def recall(request: Request, payload: RecallRequest) -> list[dict[str, Any]]:
        return active_service(request).recall(payload)

    @app.post("/answer")
    def answer(request: Request, payload: AnswerRequest) -> dict[str, Any]:
        return active_service(request).answer(payload, active_router()).model_dump(mode="json")

    register_currency_report_routes(app, active_service)

    @app.get("/currency/{item_id}")
    def currency(request: Request, item_id: str) -> dict[str, Any]:
        return active_service(request).evaluate_currency(item_id)

    @app.post("/verification/{item_id}")
    def verification(request: Request, item_id: str, payload: VerificationRequest) -> dict[str, Any]:
        return active_service(request).record_verification(item_id, payload).model_dump(mode="json")

    @app.post("/authorities/{authority_id}/changes")
    def authority_change(request: Request, authority_id: str, payload: AuthorityChangeRequest) -> dict[str, Any]:
        return active_service(request).register_authority_change(authority_id, payload)

    @app.post("/authority-events")
    def authority_event(request: Request, payload: AuthorityEventRequest) -> dict[str, Any]:
        return active_service(request).register_authority_event(payload)

    @app.get("/authority-polls/dead-letters")
    def authority_poll_dead_letters(request: Request, limit: int = 100) -> list[dict[str, Any]]:
        return [
            dead_letter.model_dump(mode="json")
            for dead_letter in active_service(request).authority_poll_dead_letters(limit=limit)
        ]

    @app.post("/authority-polls/dead-letters/{event_id}/retry")
    def retry_authority_poll_dead_letter(request: Request, event_id: str) -> dict[str, Any]:
        return active_service(request).retry_authority_poll_dead_letter(event_id).model_dump(mode="json")

    @app.get("/review-tasks")
    def review_tasks(
        request: Request,
        reviewer_id: str | None = None,
        state: ReviewTaskState | None = None,
    ) -> list[dict[str, Any]]:
        tasks = active_service(request).review_tasks(reviewer_id=reviewer_id, state=state)
        return [task.model_dump(mode="json") for task in tasks]

    @app.post("/review-tasks/{task_id}/assign")
    def assign_review_task(
        request: Request,
        task_id: str,
        payload: ReviewTaskAssignmentRequest,
    ) -> dict[str, Any]:
        return active_service(request).assign_review_task(task_id, payload).model_dump(mode="json")

    @app.post("/review-tasks/{task_id}/start")
    def start_review_task(
        request: Request,
        task_id: str,
        payload: ReviewTaskStartRequest,
    ) -> dict[str, Any]:
        return active_service(request).start_review_task(task_id, payload).model_dump(mode="json")

    @app.post("/review-tasks/{task_id}/resolve")
    def resolve_review_task(
        request: Request,
        task_id: str,
        payload: ReviewTaskResolutionRequest,
    ) -> dict[str, Any]:
        return active_service(request).resolve_review_task(task_id, payload).model_dump(mode="json")

    @app.post("/contest/{item_id}")
    def contest(request: Request, item_id: str, payload: ContestRequest) -> dict[str, Any]:
        return active_service(request).contest(item_id, payload).model_dump(mode="json")

    @app.post("/affirm/{item_id}")
    def affirm(request: Request, item_id: str, payload: AffirmRequest) -> dict[str, Any]:
        return active_service(request).affirm(item_id, payload).model_dump(mode="json")

    @app.post("/pin/{item_id}")
    def pin(request: Request, item_id: str, payload: PinRequest) -> dict[str, Any]:
        return active_service(request).pin(item_id, payload).model_dump(mode="json")

    @app.post("/dependencies")
    def add_dependency(request: Request, payload: DependencyRequest) -> dict[str, Any]:
        return active_service(request).add_dependency(payload).model_dump(mode="json")

    @app.post("/dependencies/suggest")
    def suggest_dependencies(request: Request, payload: DependencySuggestionRequest) -> list[dict[str, Any]]:
        return [
            suggestion.model_dump(mode="json")
            for suggestion in active_service(request).suggest_dependencies(payload, router=active_router())
        ]

    @app.get("/dependencies/suggestions")
    def dependency_suggestions(
        request: Request,
        item_id: str | None = None,
        decision: SuggestionDecision | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return [
            suggestion.model_dump(mode="json")
            for suggestion in active_service(request).dependency_suggestions(
                item_id=item_id,
                decision=decision,
                limit=limit,
            )
        ]

    @app.post("/dependencies/suggestions/{suggestion_id}/confirm")
    def confirm_dependency_suggestion(
        request: Request,
        suggestion_id: str,
        payload: DependencySuggestionDecisionRequest,
    ) -> dict[str, Any]:
        return active_service(request).confirm_dependency_suggestion(suggestion_id, payload).model_dump(mode="json")

    @app.post("/dependencies/suggestions/{suggestion_id}/reject")
    def reject_dependency_suggestion(
        request: Request,
        suggestion_id: str,
        payload: DependencySuggestionDecisionRequest,
    ) -> dict[str, Any]:
        return active_service(request).reject_dependency_suggestion(suggestion_id, payload).model_dump(mode="json")

    @app.post("/plans/execute")
    def execute_plan(request: Request, payload: PrimitivePlanRequest) -> dict[str, Any]:
        return active_service(request).execute_plan(payload).model_dump(mode="json")

    @app.get("/impact/{authority_id}")
    def impact(request: Request, authority_id: str) -> dict[str, Any]:
        return active_service(request).impact_query(authority_id)

    @app.get("/graph", response_class=PlainTextResponse)
    def dependency_graph(
        request: Request,
        output_format: str = "mermaid",
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> str:
        if output_format not in {"mermaid", "dot"}:
            return "unsupported graph format"
        return active_service(request).dependency_graph(
            output_format=cast(GraphFormat, output_format),
            matter_id=matter_id,
            client_id=client_id,
        )

    @app.post("/references/extract")
    def extract_references(request: Request, payload: ReferenceExtractionRequest) -> dict[str, Any]:
        return active_service(request).extract_references(payload).model_dump(mode="json")

    @app.post("/staleness/predict")
    def predict_staleness(request: Request, payload: StalenessPredictionRequest) -> dict[str, Any]:
        return active_service(request).predict_staleness(payload).model_dump(mode="json")

    @app.get("/why/{item_id}")
    def why(request: Request, item_id: str) -> dict[str, Any]:
        return active_service(request).why(item_id).model_dump(mode="json")

    @app.post("/timeline")
    def timeline(request: Request, payload: RecallRequest, as_of: str) -> list[dict[str, Any]]:
        return active_service(request).timeline(payload, as_of=as_of)

    return app


def _model_router_from_settings(settings: Settings) -> ModelRouter:
    local = LocalModelEndpoint(url=settings.local_model_url, model=settings.local_model_name)
    remote: ModelEndpoint
    if settings.remote_model_provider == "openai-responses" and settings.remote_model_api_key:
        remote = OpenAIResponsesEndpoint(
            url=settings.remote_model_url or "https://api.openai.com/v1/responses",
            api_key=settings.remote_model_api_key,
            model=settings.remote_model_name,
        )
    else:
        remote = RemoteZDREndpoint(url=settings.remote_model_url or settings.local_model_url)
    return ModelRouter(
        remote=remote,
        local=local,
        policy=RoutingPolicy(
            remote_allowed=settings.allow_remote_egress and settings.remote_model_url is not None,
            zero_egress_mode=settings.zero_egress_mode,
        ),
    )


def _service_database_url(settings: Settings, data_dir: Path) -> str:
    if _is_postgres_url(settings.database_url):
        return settings.database_url
    if settings.database_url != DEFAULT_DATABASE_URL:
        return settings.database_url
    return str(data_dir / "solomon.sqlite3")


def _postgres_schema_for_tenant(settings: Settings, tenant_id: str) -> str | None:
    if not _is_postgres_url(settings.database_url):
        return None
    safe_tenant_id = re.sub(r"[^A-Za-z0-9_]", "_", tenant_id).lower()
    if len(safe_tenant_id) > 57:
        suffix = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:8]
        safe_tenant_id = f"{safe_tenant_id[:48]}_{suffix}"
    return f"tenant_{safe_tenant_id}"


def _is_postgres_url(database_url: str) -> bool:
    return urlparse(database_url).scheme in {"postgres", "postgresql"}


def _is_admin_path(path: str) -> bool:
    return (
        path == "/diagnostics"
        or path == TENANT_MANAGEMENT_PREFIX
        or path.startswith(f"{TENANT_MANAGEMENT_PREFIX}/")
        or path == "/service-principals"
        or path.startswith("/service-principals/")
    )


def _oidc_validator_from_settings(settings: Settings) -> OIDCValidator | None:
    if settings.oidc_issuer is None or settings.oidc_audience is None:
        return None
    return OIDCValidator(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        clock_skew_seconds=settings.oidc_clock_skew_seconds,
        cache_seconds=settings.oidc_jwks_cache_seconds,
    )


def _bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization")
    if authorization is None:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _validate_oidc_request(request: Request, validator: OIDCValidator | None) -> OIDCIdentity | None:
    token = _bearer_token(request)
    if token is None or validator is None:
        return None
    try:
        return validator.validate(token)
    except OIDCValidationError:
        return None


def _oidc_principal_for_request(
    request: Request,
    validator: OIDCValidator | None,
    settings: Settings,
    service: SolomonService,
    *,
    tenant_id: str | None,
    required_scope: str,
) -> AuthPrincipal | None:
    if _bearer_token(request) is None or validator is None:
        return None
    correlation_id = _correlation_id(request)
    request.state.correlation_id = correlation_id
    identity = _validate_oidc_request(request, validator)
    principal = _oidc_principal(identity, tenant_id, settings) if identity is not None else None
    _record_oidc_decision(
        service,
        decision="allowed" if principal is not None and principal.has_scope(required_scope) else "denied",
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        actor_id=identity.subject if identity is not None else None,
        roles=principal.roles if principal is not None else frozenset(),
    )
    return principal


def _correlation_id(request: Request) -> str:
    return request.headers.get("x-correlation-id") or uuid.uuid4().hex


def _record_oidc_decision(
    service: SolomonService,
    *,
    decision: str,
    tenant_id: str | None,
    correlation_id: str,
    actor_id: str | None = None,
    roles: frozenset[str] = frozenset(),
) -> None:
    service.audit.append(
        "oidc_authentication",
        {"decision": decision, "tenant_id": tenant_id, "roles": sorted(roles)},
        attribution=AuditAttribution(actor_id=actor_id, correlation_id=correlation_id),
    )


def _oidc_principal(identity: OIDCIdentity, tenant_id: str | None, settings: Settings) -> AuthPrincipal | None:
    roles = mapped_oidc_roles(
        identity.claims,
        claim_name=settings.oidc_role_claim,
        mappings=settings.oidc_role_mappings,
    )
    if not roles:
        return None
    return AuthPrincipal(
        subject=identity.subject,
        role=primary_role(roles),
        tenant_id=tenant_id,
        scopes=scopes_for_roles(roles),
        roles=roles,
    )


def _admin_principal(settings: Settings, supplied_api_key: str | None) -> AuthPrincipal | None:
    if settings.server_auth_mode != "legacy-api-key" and settings.oidc_issuer is not None:
        return None
    if not static_secret_matches(settings.server_api_key, supplied_api_key):
        return None
    return AuthPrincipal(
        subject="server-admin",
        role="admin",
        tenant_id=None,
        scopes=ADMIN_AUTH_SCOPES,
    )


def _tenant_principal(
    settings: Settings,
    tenant_registry: TenantRegistry,
    record: TenantRecord,
    tenant_id: str,
    supplied_api_key: str | None,
) -> AuthPrincipal | None:
    if settings.server_auth_mode != "legacy-api-key" and settings.oidc_issuer is not None:
        return None
    admin = _admin_principal(settings, supplied_api_key)
    if admin is not None:
        return admin
    if tenant_registry.verify_tenant_api_key(record, supplied_api_key):
        return AuthPrincipal(
            subject=f"tenant:{tenant_id}",
            role="tenant",
            tenant_id=tenant_id,
            scopes=frozenset(record.api_key_scopes),
        )
    return None


def _service_principal(
    registry: ServicePrincipalRegistry,
    tenant_id: str,
    request: Request,
) -> AuthPrincipal | None:
    record = registry.authenticate(tenant_id=tenant_id, credential=_service_principal_credential(request))
    if record is None:
        return None
    return AuthPrincipal(
        subject=f"service-principal:{record.principal_id}",
        role="integration",
        tenant_id=tenant_id,
        scopes=frozenset(record.scopes),
        roles=frozenset({"integration"}),
    )


def _service_principal_credential(request: Request) -> str | None:
    credential = request.headers.get("x-api-key")
    return credential if credential and credential.startswith("solomon_sp_") else None


def _record_service_principal_decision(
    service: SolomonService,
    principal: AuthPrincipal | None,
    tenant_id: str,
    correlation_id: str,
    decision: str,
) -> None:
    service.audit.append(
        "service_principal_authentication",
        {"tenant_id": tenant_id, "decision": decision, "scopes": sorted(principal.scopes) if principal else []},
        attribution=AuditAttribution(
            actor_id=principal.subject if principal is not None else None,
            correlation_id=correlation_id,
        ),
    )


def _record_service_principal_lifecycle(
    service: SolomonService,
    request: Request,
    decision: str,
    record: ServicePrincipalRecord,
) -> None:
    principal = cast(AuthPrincipal, request.state.principal)
    service.audit.append(
        "service_principal_lifecycle",
        {
            "principal_id": record.principal_id,
            "tenant_id": record.tenant_id,
            "decision": decision,
            "status": record.status,
            "scopes": record.scopes,
        },
        attribution=AuditAttribution(actor_id=principal.subject, correlation_id=request.state.correlation_id),
    )


def _auth_error() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"error": {"code": "unauthorized", "message": "invalid or missing credentials"}},
    )


def _forbidden_error(required_scope: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"error": {"code": "forbidden", "message": f"required scope: {required_scope}"}},
    )


def _tenant_response(record: TenantRecord) -> TenantResponse:
    return TenantResponse(
        tenant_id=record.tenant_id,
        display_name=record.display_name,
        status=record.status,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
        api_key_configured=record.api_key_configured,
        api_key_scopes=list(record.api_key_scopes),
    )


def _service_principal_response(record: ServicePrincipalRecord) -> ServicePrincipalResponse:
    return ServicePrincipalResponse(
        principal_id=record.principal_id,
        tenant_id=record.tenant_id,
        status=record.status,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
        scopes=record.scopes,
    )
app = create_app()
