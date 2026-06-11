# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from solomon import __version__
from solomon.boundary.kaypoh import KaypohImportStatus, probe_kaypoh_client
from solomon.config import Settings, get_settings


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
    app = FastAPI(
        title="Solomon",
        version=__version__,
        summary="Good-law engine for firm knowledge behind a Kaypoh boundary.",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.settings = resolved_settings

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

    return app


app = create_app()

