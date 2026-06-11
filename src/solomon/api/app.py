# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from solomon import __version__
from solomon.api.service import (
    AuthorityChangeRequest,
    DependencyRequest,
    IngestRequest,
    RecallRequest,
    SolomonService,
    VerificationRequest,
)
from solomon.boundary.kaypoh import KaypohImportStatus, probe_kaypoh_client
from solomon.config import Settings, get_settings
from solomon.errors import SolomonError


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
    service = SolomonService(data_dir=resolved_settings.data_dir, journal_dir=resolved_settings.journal_dir)
    app = FastAPI(
        title="Solomon",
        version=__version__,
        summary="Good-law engine for firm knowledge behind a Kaypoh boundary.",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.settings = resolved_settings
    app.state.service = service

    @app.middleware("http")
    async def server_api_key_middleware(request: Request, call_next: Any) -> Any:
        if (
            resolved_settings.sku == "server"
            and resolved_settings.server_api_key
            and request.url.path not in {"/health", "/ready"}
        ):
            supplied = request.headers.get("x-api-key")
            if supplied != resolved_settings.server_api_key:
                return JSONResponse(
                    status_code=401,
                    content={"error": {"code": "unauthorized", "message": "invalid or missing API key"}},
                )
            request.state.tenant_id = request.headers.get("x-tenant-id", "default")
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
    def ingest(request: IngestRequest) -> dict[str, Any]:
        return service.ingest(request).model_dump(mode="json")

    @app.post("/recall")
    def recall(request: RecallRequest) -> list[dict[str, Any]]:
        return service.recall(request)

    @app.get("/currency/{item_id}")
    def currency(item_id: str) -> dict[str, Any]:
        return service.evaluate_currency(item_id)

    @app.post("/verification/{item_id}")
    def verification(item_id: str, request: VerificationRequest) -> dict[str, Any]:
        return service.record_verification(item_id, request).model_dump(mode="json")

    @app.post("/authorities/{authority_id}/changes")
    def authority_change(authority_id: str, request: AuthorityChangeRequest) -> dict[str, Any]:
        return service.register_authority_change(authority_id, request)

    @app.post("/dependencies")
    def add_dependency(request: DependencyRequest) -> dict[str, Any]:
        return service.add_dependency(request).model_dump(mode="json")

    @app.get("/impact/{authority_id}")
    def impact(authority_id: str) -> dict[str, Any]:
        return service.impact_query(authority_id)

    @app.get("/why/{item_id}")
    def why(item_id: str) -> dict[str, Any]:
        return service.why(item_id).model_dump(mode="json")

    @app.post("/timeline")
    def timeline(request: RecallRequest, as_of: str) -> list[dict[str, Any]]:
        return service.timeline(request, as_of=as_of)

    return app


app = create_app()
