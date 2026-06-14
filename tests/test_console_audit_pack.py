# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import anyio
import httpx

from solomon.api.service import IngestRequest, SolomonService
from solomon.console.app import create_console_app
from solomon.currency.models import KnowledgeKind, SourceKind


def test_audit_pack_screen_loads_item(tmp_path: Path) -> None:
    service, item_id = _audit_service(tmp_path)

    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_console_app(service=service))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(f"/console/audit-pack?item_id={item_id}")

    response = anyio.run(call)

    assert response.status_code == 200
    assert "Audit Pack" in response.text
    assert 'class="tab active" href="/console/audit-pack"' in response.text
    assert item_id in response.text
    assert "Export JSON" in response.text
    assert "Export PDF" in response.text


def test_audit_pack_exports_json_and_pdf(tmp_path: Path) -> None:
    service, item_id = _audit_service(tmp_path)

    async def call() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=create_console_app(service=service))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            json_response = await client.get(f"/console/audit-pack/items/{item_id}/export?format=json")
            pdf_response = await client.get(f"/console/audit-pack/items/{item_id}/export?format=pdf")
            return json_response, pdf_response

    json_response, pdf_response = anyio.run(call)

    pack = json.loads(json_response.text)
    assert json_response.status_code == 200
    assert pack["schema"] == "solomon.console.audit_pack.v1"
    assert pack["knowledge_item_id"] == item_id
    assert pack["manifest"]["schema"] == "solomon.audit_pack.v1"
    assert "journal_jsonl" in pack
    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"] == "application/pdf"
    assert pdf_response.content.startswith(b"%PDF-1.4")


def _audit_service(tmp_path: Path) -> tuple[SolomonService, str]:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x under Regulation R section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-audit",
            matter_id="matter-a",
            client_id="client-a",
        )
    )
    return service, item.id
