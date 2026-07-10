# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import anyio
import httpx

from solomon.api.service import AuthorityChangeRequest, DependencyRequest, IngestRequest, SolomonService
from solomon.console.app import create_console_app
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.models import EdgeType


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


def test_currency_report_screen_and_exports(tmp_path: Path) -> None:
    service, item_id = _currency_report_service(tmp_path)
    params = {
        "period_start": "2026-01-01T00:00:00+00:00",
        "period_end": "2026-12-31T00:00:00+00:00",
        "scope": "matter",
        "matter_id": "matter-a",
        "client_id": "client-a",
    }

    async def call() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=create_console_app(service=service))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            screen = await client.get("/console/currency-report", params=params)
            json_response = await client.get("/console/currency-report/export", params={**params, "format": "json"})
            pdf_response = await client.get("/console/currency-report/export", params={**params, "format": "pdf"})
            return screen, json_response, pdf_response

    screen, json_response, pdf_response = anyio.run(call)

    assert screen.status_code == 200
    assert "Currency Report" in screen.text
    assert item_id in screen.text
    assert "Export JSON" in screen.text
    payload = json.loads(json_response.text)
    assert payload["schema"] == "solomon.console.currency_report_pack.v1"
    assert payload["manifest"]["currency_report_file"] == "currency-report.json"
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


def _currency_report_service(tmp_path: Path) -> tuple[SolomonService, str]:
    service, item_id = _audit_service(tmp_path)
    service.add_dependency(
        DependencyRequest(
            source_id=item_id,
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )
    service.register_authority_change(
        "reg-r-12",
        AuthorityChangeRequest(new_version="2026", changed_at="2026-01-05T00:00:00+00:00"),
    )
    return service, item_id
