# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from solomon.api.app import create_app
from solomon.api.service import (
    AuthorityChangeRequest,
    DependencyRequest,
    IngestRequest,
    RecallRequest,
    SolomonService,
    VerificationRequest,
)
from solomon.client import SolomonClient
from solomon.config import Settings
from solomon.currency.engine import VerificationOutcome
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.models import EdgeType


def test_service_ingest_recall_why_and_timeline(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x under regulation r section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo",
        )
    )

    recall = service.recall(RecallRequest(query="structure x regulation"))
    why = service.why(item.id)
    timeline = service.timeline(RecallRequest(query="structure x"), as_of=item.ingested_at.isoformat())

    assert recall[0]["item"]["id"] == item.id
    assert why.item.id == item.id
    assert timeline[0]["item"]["id"] == item.id


def test_service_currency_cache_invalidates_after_dependency_change(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x under regulation r section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo",
        )
    )
    service.add_dependency(
        DependencyRequest(
            source_id=item.id,
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )

    assert service.evaluate_currency(item.id)["currency_state"] == "StalePendingReverification"
    assert service.currency_cache.contains(item.id)

    service.register_authority_change(
        "reg-r-12",
        AuthorityChangeRequest(new_version="2025", changed_at="2025-01-01T00:00:00+00:00"),
    )

    assert not service.currency_cache.contains(item.id)
    assert service.evaluate_currency(item.id)["currency_state"] == "StalePendingReverification"


def test_service_records_signed_verification_attestation_when_configured(tmp_path: Path) -> None:
    service = SolomonService(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        attestation_key="test-secret",
    )
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="verified position",
            source_kind=SourceKind.PARTNER,
            source_ref="memo",
        )
    )

    service.record_verification(item.id, VerificationRequest(by="Partner A", outcome=VerificationOutcome.REAFFIRM))

    raw = (tmp_path / "journal" / "journal.jsonl").read_text(encoding="utf-8")
    assert "verification_attestation" in raw
    assert "verified position" not in raw


def test_fastapi_app_exposes_public_verbs(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal"))
    paths = {getattr(route, "path", "") for route in app.routes}

    assert {
        "/ingest",
        "/recall",
        "/currency/{item_id}",
        "/verification/{item_id}",
        "/authorities/{authority_id}/changes",
        "/impact/{authority_id}",
        "/graph",
        "/references/extract",
        "/staleness/predict",
        "/why/{item_id}",
        "/timeline",
    }.issubset(paths)


def test_server_mode_requires_and_isolates_tenants(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            sku="server",
            zero_egress_mode=False,
            data_dir=tmp_path / "data",
            journal_dir=tmp_path / "journal",
            server_api_key="secret",
        )
    )
    tenant_a = {"x-api-key": "secret", "x-tenant-id": "tenant-a"}
    tenant_b = {"x-api-key": "secret", "x-tenant-id": "tenant-b"}
    payload = {
        "kind": "position",
        "content": "tenant alpha position",
        "source_kind": "partner",
        "source_ref": "memo-a",
    }

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            missing_tenant = await client.post("/ingest", headers={"x-api-key": "secret"}, json=payload)
            created = await client.post("/ingest", headers=tenant_a, json=payload)
            tenant_a_recall = await client.post(
                "/recall",
                headers=tenant_a,
                json={"query": "tenant alpha", "review_mode": True},
            )
            tenant_b_recall = await client.post(
                "/recall",
                headers=tenant_b,
                json={"query": "tenant alpha", "review_mode": True},
            )
            return missing_tenant, created, tenant_a_recall, tenant_b_recall

    missing_tenant, created, tenant_a_recall, tenant_b_recall = asyncio.run(exercise())

    assert missing_tenant.status_code == 400
    assert created.status_code == 200
    assert len(tenant_a_recall.json()) == 1
    assert tenant_b_recall.json() == []
    assert (tmp_path / "data" / "tenants" / "tenant-a" / "solomon.sqlite3").exists()
    assert (tmp_path / "data" / "tenants" / "tenant-b" / "solomon.sqlite3").exists()


def test_sync_client_uses_httpx_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ingest":
            payload: dict[str, Any] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"id": "item-1", **payload})
        if request.url.path == "/recall":
            return httpx.Response(200, json=[{"item": {"id": "item-1"}}])
        if request.url.path == "/why/item-1":
            return httpx.Response(200, json={"item": {"id": "item-1"}})
        return httpx.Response(404)

    with SolomonClient(transport=httpx.MockTransport(handler)) as client:
        assert client.ingest({"content": "x"})["id"] == "item-1"
        assert client.recall({"query": "x"})[0]["item"]["id"] == "item-1"
        assert client.why("item-1")["item"]["id"] == "item-1"
