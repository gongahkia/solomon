# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import anyio
import httpx

from solomon.api.service import IngestRequest, SolomonService
from solomon.console.app import create_console_app
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.suggestions import SuggestionDecision


def test_dependency_review_lists_pending_suggestions(tmp_path: Path) -> None:
    service = _dependency_service(tmp_path)
    suggestion = service.dependency_suggestions()[0]

    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_console_app(service=service))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get("/console/dependencies")

    response = anyio.run(call)

    assert response.status_code == 200
    assert "Dependency Review" in response.text
    assert suggestion.id in response.text
    assert "regulation-r-section-12" in response.text


def test_dependency_review_accepts_suggestion(tmp_path: Path) -> None:
    service = _dependency_service(tmp_path)
    suggestion = service.dependency_suggestions()[0]

    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_console_app(service=service))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                f"/console/dependencies/suggestions/{suggestion.id}/confirm",
                data={"reviewer_id": "Partner A"},
            )

    response = anyio.run(call)

    assert response.status_code == 200
    assert service.dependency_suggestions(item_id=suggestion.item_id, decision=SuggestionDecision.CONFIRMED)
    assert service.graph.get_dependencies(suggestion.item_id)


def _dependency_service(tmp_path: Path) -> SolomonService:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="Regulation R section 12 controls. Regulation S section 9 also matters.",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-deps",
            matter_id="matter-a",
            client_id="client-a",
        )
    )
    return service
