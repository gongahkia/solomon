# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from solomon import __version__
from solomon.api.auth import (
    ADMIN_AUTH_SCOPES,
    AuthPrincipal,
    extract_api_key,
    required_scope_for_request,
    static_secret_matches,
    validate_auth_scopes,
)
from solomon.api.report_routes import register_currency_report_routes
from solomon.api.service import (
    AffirmRequest,
    AnswerRequest,
    AuthorityChangeRequest,
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
    SolomonService,
    StalenessPredictionRequest,
    VerificationRequest,
)
from solomon.api.tenancy import (
    TenantAlreadyExistsError,
    TenantNotFoundError,
    TenantRecord,
    TenantRegistry,
    is_valid_tenant_id,
)
from solomon.boundary.solomon import BoundaryImportStatus, SolomonBoundary, probe_boundary_client
from solomon.config import (
    Settings,
    boundary_policy_from_settings,
    credence_policy_from_settings,
    get_settings,
    verification_policy_from_settings,
)
from solomon.errors import SolomonError
from solomon.graph.suggestions import SuggestionDecision
from solomon.graph.visualization import GraphFormat
from solomon.orchestrator.models import (
    LocalModelEndpoint,
    ModelEndpoint,
    ModelRouter,
    OpenAIResponsesEndpoint,
    RemoteZDREndpoint,
    RoutingPolicy,
)

PUBLIC_PATHS = {"/health", "/ready", "/docs", "/redoc", "/openapi.json"}
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


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    tenant_registry = TenantRegistry(resolved_settings.data_dir / "tenants" / "registry.json")
    vp = verification_policy_from_settings(resolved_settings)
    cp = credence_policy_from_settings(resolved_settings)
    service = SolomonService(
        data_dir=resolved_settings.data_dir,
        journal_dir=resolved_settings.journal_dir,
        attestation_key=resolved_settings.verification_attestation_key,
        database_url=_service_database_url(resolved_settings, resolved_settings.data_dir),
        verification_policy=vp, verification_policy_version=resolved_settings.verification_policy_version,
        credence_policy=cp, credence_policy_version=resolved_settings.credence_policy_version,
        boundary=SolomonBoundary(policy=boundary_policy_from_settings(resolved_settings)),
    )
    tenant_services: dict[str, SolomonService] = {}

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
            boundary=SolomonBoundary(policy=boundary_policy_from_settings(resolved_settings)),
        )
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
            if _is_admin_path(path):
                principal = _admin_principal(resolved_settings, supplied_api_key)
                if principal is None:
                    return _auth_error()
                if not principal.has_scope(required_scope):
                    return _forbidden_error(required_scope)
                request.state.principal = principal
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
            principal = _tenant_principal(resolved_settings, tenant_registry, record, tenant_id, supplied_api_key)
            if principal is None:
                return _auth_error()
            if not principal.has_scope(required_scope):
                return _forbidden_error(required_scope)
            request.state.tenant_id = tenant_id
            request.state.service = service_for_tenant(tenant_id)
            request.state.principal = principal
        return await call_next(request)

    @app.exception_handler(SolomonError)
    def solomon_error_handler(_request: Request, exc: SolomonError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/ready", response_model=ReadyResponse)
    def ready() -> ReadyResponse:
        boundary = probe_boundary_client(resolved_settings.boundary_engine_path)
        return ReadyResponse(ready=boundary.importable, boundary_client_importable=boundary.importable)

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

    @app.post("/ingest")
    def ingest(request: Request, payload: IngestRequest) -> dict[str, Any]:
        return active_service(request).ingest(payload).model_dump(mode="json")

    @app.post("/sources")
    def register_document_source(request: Request, payload: DocumentSourceRequest) -> dict[str, Any]:
        return active_service(request).register_document_source(payload).model_dump(mode="json")

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
    return path == "/diagnostics" or path == TENANT_MANAGEMENT_PREFIX or path.startswith(f"{TENANT_MANAGEMENT_PREFIX}/")


def _admin_principal(settings: Settings, supplied_api_key: str | None) -> AuthPrincipal | None:
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


def _auth_error() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"error": {"code": "unauthorized", "message": "invalid or missing API key"}},
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
app = create_app()
