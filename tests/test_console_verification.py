# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import anyio
import httpx

from solomon.api.service import AuthorityChangeRequest, DependencyRequest, IngestRequest, SolomonService
from solomon.console.app import create_console_app
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.models import EdgeType


def test_verification_desk_lists_stale_items(tmp_path: Path) -> None:
    service, item_id = _stale_service(tmp_path)

    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_console_app(service=service))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get("/console/verification")

    response = anyio.run(call)

    assert response.status_code == 200
    assert "Verification Desk" in response.text
    assert item_id in response.text
    assert "StalePendingReverification" in response.text


def test_verification_desk_reaffirms_item(tmp_path: Path) -> None:
    service, item_id = _stale_service(tmp_path)

    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_console_app(service=service))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                f"/console/verification/items/{item_id}/decision",
                data={"decision": "reaffirm", "partner_id": "Partner A", "evidence_ref": "memo-2"},
            )

    response = anyio.run(call)

    assert response.status_code == 200
    assert "Live" in response.text
    assert service.evaluate_currency(item_id)["currency_state"] == "Live"


def _stale_service(tmp_path: Path) -> tuple[SolomonService, str]:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x depends on Regulation R section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-1",
            matter_id="matter-a",
            client_id="client-a",
        )
    )
    service.add_dependency(
        DependencyRequest(
            source_id=item.id,
            target_id="regulation-r-section-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )
    service.register_authority_change(
        "regulation-r-section-12",
        AuthorityChangeRequest(new_version="v2", changed_at="2026-01-01T00:00:00+00:00"),
    )
    return service, item.id
