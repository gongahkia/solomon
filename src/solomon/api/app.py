# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from solomon import __version__
from solomon.api.service import (
    AnswerRequest,
    AuthorityChangeRequest,
    DependencyRequest,
    IngestRequest,
    RecallRequest,
    ReferenceExtractionRequest,
    SolomonService,
    StalenessPredictionRequest,
    VerificationRequest,
)
from solomon.boundary.kaypoh import KaypohImportStatus, probe_kaypoh_client
from solomon.config import Settings, get_settings
from solomon.errors import SolomonError
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
TENANT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
DEFAULT_DATABASE_URL = str(Settings.model_fields["database_url"].default)


class HealthResponse(BaseModel):
    status: str = Field(..., examples=["ok"])
    service: str = "solomon"
    version: str = __version__


class ReadyResponse(BaseModel):
    ready: bool
    kaypoh_client_importable: bool


class DiagnosticsResponse(BaseModel):
    service: str = "solomon"
    version: str = __version__
    kaypoh: KaypohImportStatus
    settings: dict[str, Any]


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    service = SolomonService(
        data_dir=resolved_settings.data_dir,
        journal_dir=resolved_settings.journal_dir,
        attestation_key=resolved_settings.verification_attestation_key,
        database_url=_service_database_url(resolved_settings, resolved_settings.data_dir),
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
            database_url=_service_database_url(
                resolved_settings,
                resolved_settings.data_dir / "tenants" / tenant_id,
            ),
            postgres_schema=_postgres_schema_for_tenant(resolved_settings, tenant_id),
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
        summary="Good-law engine for firm knowledge behind a Kaypoh boundary.",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.settings = resolved_settings
    app.state.service = service
    app.state.router = _model_router_from_settings(resolved_settings)

    def active_router() -> ModelRouter:
        resolved = getattr(app.state, "router", None)
        if isinstance(resolved, ModelRouter):
            return resolved
        return _model_router_from_settings(resolved_settings)

    @app.middleware("http")
    async def server_api_key_middleware(request: Request, call_next: Any) -> Any:
        request.state.tenant_id = "local"
        request.state.service = service
        if resolved_settings.sku == "server" and request.url.path not in PUBLIC_PATHS:
            if resolved_settings.server_api_key:
                supplied = request.headers.get("x-api-key")
                if supplied != resolved_settings.server_api_key:
                    return JSONResponse(
                        status_code=401,
                        content={"error": {"code": "unauthorized", "message": "invalid or missing API key"}},
                    )
            tenant_id = request.headers.get("x-tenant-id")
            if tenant_id is None or not TENANT_ID_RE.fullmatch(tenant_id):
                return JSONResponse(
                    status_code=400,
                    content={"error": {"code": "invalid_tenant", "message": "valid x-tenant-id header required"}},
                )
            request.state.tenant_id = tenant_id
            request.state.service = service_for_tenant(tenant_id)
        return await call_next(request)

    @app.exception_handler(SolomonError)
    def solomon_error_handler(_request: Request, exc: SolomonError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/ready", response_model=ReadyResponse)
    def ready() -> ReadyResponse:
        kaypoh = probe_kaypoh_client(resolved_settings.kaypoh_repo_path)
        return ReadyResponse(ready=kaypoh.importable, kaypoh_client_importable=kaypoh.importable)

    @app.get("/diagnostics", response_model=DiagnosticsResponse)
    def diagnostics() -> DiagnosticsResponse:
        return DiagnosticsResponse(
            kaypoh=probe_kaypoh_client(resolved_settings.kaypoh_repo_path),
            settings=resolved_settings.public_diagnostics(),
        )

    @app.post("/ingest")
    def ingest(request: Request, payload: IngestRequest) -> dict[str, Any]:
        return active_service(request).ingest(payload).model_dump(mode="json")

    @app.post("/recall")
    def recall(request: Request, payload: RecallRequest) -> list[dict[str, Any]]:
        return active_service(request).recall(payload)

    @app.post("/answer")
    def answer(request: Request, payload: AnswerRequest) -> dict[str, Any]:
        return active_service(request).answer(payload, active_router()).model_dump(mode="json")

    @app.get("/currency/{item_id}")
    def currency(request: Request, item_id: str) -> dict[str, Any]:
        return active_service(request).evaluate_currency(item_id)

    @app.post("/verification/{item_id}")
    def verification(request: Request, item_id: str, payload: VerificationRequest) -> dict[str, Any]:
        return active_service(request).record_verification(item_id, payload).model_dump(mode="json")

    @app.post("/authorities/{authority_id}/changes")
    def authority_change(request: Request, authority_id: str, payload: AuthorityChangeRequest) -> dict[str, Any]:
        return active_service(request).register_authority_change(authority_id, payload)

    @app.post("/dependencies")
    def add_dependency(request: Request, payload: DependencyRequest) -> dict[str, Any]:
        return active_service(request).add_dependency(payload).model_dump(mode="json")

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
    local = LocalModelEndpoint(url=settings.local_model_url)
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
    return f"tenant_{tenant_id}"


def _is_postgres_url(database_url: str) -> bool:
    return urlparse(database_url).scheme in {"postgres", "postgresql"}


app = create_app()
