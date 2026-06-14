# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

from solomon.api.app import create_app
from solomon.api.service import (
    AuthorityChangeRequest,
    DependencyRequest,
    IngestRequest,
    RecallRequest,
    SolomonService,
    VerificationRequest,
)
from solomon.boundary.engine.client import BoundaryClient
from solomon.boundary.solomon import BoundaryUnavailableError, SolomonBoundary
from solomon.client import AsyncSolomonClient, SolomonAPIError, SolomonClient
from solomon.config import Settings
from solomon.currency.engine import VerificationOutcome
from solomon.currency.models import CredenceTier, KnowledgeItem, KnowledgeKind, Provenance, SourceKind
from solomon.graph.models import EdgeType
from solomon.orchestrator.models import EndpointKind, ModelRequest, ModelResponse, ModelRouter


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


def test_service_ingest_calls_vendored_boundary_and_attaches_findings(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")

    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="Position prepared for Client A under Regulation R section 12.",
            source_kind=SourceKind.PARTNER,
            source_ref="memo",
        )
    )

    assert item.provenance.boundary_review_classification == "SAFE"
    assert any(finding["kind"] == "client_reference" for finding in item.provenance.boundary_findings)


def test_service_ingest_persists_credence_audit_without_content(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")

    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="privileged client strategy",
            source_kind=SourceKind.PARTNER,
            source_ref="memo",
        )
    )

    raw = (tmp_path / "journal" / "journal.jsonl").read_text(encoding="utf-8")
    assert "credence_change" in raw
    assert item.id in raw
    assert "FirmAuthoritative" in raw
    assert "source kind partner" in raw
    assert "privileged client strategy" not in raw


def test_service_fails_closed_when_vendored_boundary_fails_for_ingest_and_model_egress(tmp_path: Path) -> None:
    service = SolomonService(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        boundary=SolomonBoundary(BoundaryClient(fail=True)),
    )

    with pytest.raises(BoundaryUnavailableError):
        service.ingest(
            IngestRequest(
                kind=KnowledgeKind.POSITION,
                content="Client A structure x",
                source_kind=SourceKind.PARTNER,
                source_ref="memo",
            )
        )

    class CountingEndpoint:
        kind = EndpointKind.REMOTE_ZDR

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, request: ModelRequest) -> ModelResponse:
            self.calls += 1
            return ModelResponse(text=request.prompt, endpoint=self.kind)

    remote = CountingEndpoint()
    local = CountingEndpoint()
    from solomon.orchestrator.models import ModelRouter

    router = ModelRouter(remote=remote, local=local)
    with pytest.raises(BoundaryUnavailableError):
        service.complete_model_request(router, ModelRequest(prompt="Client A model context", matter_id="matter-a"))
    assert remote.calls == 0
    assert local.calls == 0


def test_service_model_call_sanitizes_before_router_and_reidentifies_after(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")

    class EchoEndpoint:
        kind = EndpointKind.REMOTE_ZDR

        def __init__(self) -> None:
            self.seen_prompt = ""

        def complete(self, request: ModelRequest) -> ModelResponse:
            self.seen_prompt = request.prompt
            return ModelResponse(text=f"Answer for {request.prompt}", endpoint=self.kind)

    remote = EchoEndpoint()
    local = EchoEndpoint()
    from solomon.orchestrator.models import ModelRouter

    result = service.complete_model_request(
        ModelRouter(remote=remote, local=local),
        ModelRequest(prompt="Advice for Client A", matter_id="matter-a"),
    )

    assert "Client A" not in remote.seen_prompt
    assert "[CLIENT_1]" in remote.seen_prompt
    assert "Client A" in result.response.text
    assert service.boundary.volatile_mapping_count() == 0


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

    assert service.evaluate_currency(item.id)["currency_state"] == "Live"
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
        "/answer",
        "/currency/{item_id}",
        "/verification/{item_id}",
        "/authorities/{authority_id}/changes",
        "/contest/{item_id}",
        "/affirm/{item_id}",
        "/pin/{item_id}",
        "/plans/execute",
        "/dependencies/suggest",
        "/dependencies/suggestions",
        "/dependencies/suggestions/{suggestion_id}/confirm",
        "/dependencies/suggestions/{suggestion_id}/reject",
        "/impact/{authority_id}",
        "/graph",
        "/references/extract",
        "/staleness/predict",
        "/why/{item_id}",
        "/timeline",
    }.issubset(paths)


def test_answer_endpoint_runs_recall_boundary_router_model_workflow(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal"))

    class CapturingEndpoint:
        kind = EndpointKind.REMOTE_ZDR

        def __init__(self) -> None:
            self.calls = 0
            self.seen_prompt = ""

        def complete(self, request: ModelRequest) -> ModelResponse:
            self.calls += 1
            self.seen_prompt = request.prompt
            return ModelResponse(text=f"Answer from {request.prompt}", endpoint=self.kind)

    remote = CapturingEndpoint()
    local = CapturingEndpoint()
    app.state.router = ModelRouter(remote=remote, local=local)

    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post(
                "/ingest",
                json={
                    "kind": "position",
                    "content": "Client A position under Regulation R section 12.",
                    "source_kind": "partner",
                    "source_ref": "memo-answer",
                    "matter_id": "matter-a",
                    "client_id": "client-a",
                },
            )
            answer = await client.post(
                "/answer",
                json={
                    "query": "Client A Regulation R",
                    "matter_id": "matter-a",
                    "client_id": "client-a",
                    "limit": 3,
                },
            )
            return created, answer

    created, answer = asyncio.run(exercise())

    assert created.status_code == 200
    assert answer.status_code == 200
    payload = answer.json()
    assert payload["recalled"][0]["item"]["id"] == created.json()["id"]
    assert payload["prompt"]["context_item_ids"] == [created.json()["id"]]
    assert payload["prompt"]["boundary_applied"] is True
    assert payload["model"]["endpoint"] == "remote_zdr"
    assert remote.calls == 1
    assert local.calls == 0
    assert "Client A" not in remote.seen_prompt
    assert "[CLIENT_1]" in remote.seen_prompt
    assert "Client A" in payload["text"]
    assert payload["primitive_plan"]["steps"][0]["primitive"] == "recall"
    assert payload["primitive_plan"]["plan"]["steps"][0]["args"]["query"] == "Client A Regulation R"
    raw_journal = (tmp_path / "journal" / "journal.jsonl").read_text(encoding="utf-8")
    assert "primitive_plan" in raw_journal
    assert "answer_workflow" in raw_journal
    assert "context_item_ids" in raw_journal
    assert "prompt_sha256" in raw_journal
    assert "Client A position under Regulation R section 12." not in raw_journal
    assert "Answer from" not in raw_journal


def test_answer_endpoint_refuses_low_credence_context_before_model_call(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal"))
    service = app.state.service
    low = KnowledgeItem(
        id="model-only",
        kind=KnowledgeKind.POSITION,
        content="model-only structure x",
        provenance=Provenance(source_kind=SourceKind.MODEL, source_ref="llm"),
        credence_tier=CredenceTier.MODEL_INFERRED,
        last_verified_at=datetime.now(tz=timezone.utc),
    )
    indexed = service.index.upsert_item(low)
    service.store.write_item(indexed)

    class CountingEndpoint:
        kind = EndpointKind.REMOTE_ZDR

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, request: ModelRequest) -> ModelResponse:
            self.calls += 1
            return ModelResponse(text="should not be called", endpoint=self.kind)

    remote = CountingEndpoint()
    local = CountingEndpoint()
    app.state.router = ModelRouter(remote=remote, local=local)

    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post("/answer", json={"query": "model-only structure"})

    response = asyncio.run(exercise())

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "policy_refusal"
    assert "ModelInferred" in response.json()["error"]["message"]
    assert remote.calls == 0
    assert local.calls == 0
    raw_journal = (tmp_path / "journal" / "journal.jsonl").read_text(encoding="utf-8")
    assert "load_bearing_refusal" in raw_journal
    assert "model-only structure x" not in raw_journal


def test_public_route_wrappers_apply_service_state_and_return_stable_shapes(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal"))

    async def exercise() -> dict[str, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post(
                "/ingest",
                json={
                    "kind": "position",
                    "content": "Original structure x under Regulation R section 12.",
                    "source_kind": "partner",
                    "source_ref": "memo-routes",
                    "valid_from": "2026-01-01T00:00:00+00:00",
                    "ingested_at": "2026-01-01T00:00:00+00:00",
                },
            )
            item_id = created.json()["id"]
            dependency = await client.post(
                "/dependencies",
                json={
                    "source_id": item_id,
                    "target_id": "reg-r-12",
                    "edge_type": "internal_depends_on_external",
                    "target_kind": "external_authority",
                    "reason": "manual route-wrapper test edge",
                },
            )
            suggested_item = await client.post(
                "/ingest",
                json={
                    "kind": "position",
                    "content": "Queue route wrapper relies on Regulation S section 9.",
                    "source_kind": "partner",
                    "source_ref": "memo-suggestion-routes",
                    "valid_from": "2026-01-01T00:00:00+00:00",
                    "ingested_at": "2026-01-01T00:00:00+00:00",
                },
            )
            suggestions = await client.get(
                "/dependencies/suggestions",
                params={"item_id": suggested_item.json()["id"], "decision": "pending"},
            )
            suggestion_id = suggestions.json()[0]["id"]
            suggest_rerun = await client.post(
                "/dependencies/suggest",
                json={"item_id": suggested_item.json()["id"]},
            )
            confirm_suggestion = await client.post(
                f"/dependencies/suggestions/{suggestion_id}/confirm",
                json={"by": "Partner A"},
            )
            rejected_item = await client.post(
                "/ingest",
                json={
                    "kind": "position",
                    "content": "Queue reject route wrapper relies on Regulation T section 3.",
                    "source_kind": "partner",
                    "source_ref": "memo-reject-routes",
                },
            )
            reject_suggestions = await client.get(
                "/dependencies/suggestions",
                params={"item_id": rejected_item.json()["id"], "decision": "pending"},
            )
            reject_suggestion = await client.post(
                f"/dependencies/suggestions/{reject_suggestions.json()[0]['id']}/reject",
                json={"by": "Partner A"},
            )
            currency = await client.get(f"/currency/{item_id}")
            plan = await client.post(
                "/plans/execute",
                json={
                    "steps": [
                        {"primitive": "recall", "args": {"query": "structure x", "review_mode": True}},
                        {"primitive": "evaluate_currency", "args": {"item_id": item_id}},
                    ]
                },
            )
            impact = await client.get("/impact/reg-r-12")
            graph = await client.get("/graph")
            references = await client.post(
                "/references/extract",
                json={"content": 'The "Covered Structure" means Regulation R section 12 treatment.'},
            )
            prediction = await client.post(
                "/staleness/predict",
                json={
                    "pending_amendments": [
                        {
                            "authority_id": "reg-r-12",
                            "expected_change_at": "2026-01-01T00:00:00+00:00",
                            "description": "Regulation R section 12 consultation",
                        }
                    ],
                    "as_of": "2025-01-01T00:00:00+00:00",
                    "lookahead_days": 400,
                },
            )
            timeline = await client.post(
                "/timeline",
                params={"as_of": created.json()["ingested_at"]},
                json={"query": "structure x", "review_mode": True},
            )
            contest = await client.post(
                f"/contest/{item_id}",
                json={
                    "lawyer_id": "Associate A",
                    "actor_tier": "Verified",
                    "reason": "Route-wrapper challenge",
                    "proposed_correction": "Corrected structure x under Regulation R section 12.",
                    "contested_at": "2026-02-01T00:00:00+00:00",
                },
            )
            correction_id = contest.json()["correction_item"]["id"]
            affirm = await client.post(
                f"/affirm/{item_id}",
                json={
                    "lawyer_id": "Partner A",
                    "actor_tier": "FirmAuthoritative",
                    "correction_item_id": correction_id,
                    "affirmed_at": "2026-02-02T00:00:00+00:00",
                },
            )
            pin = await client.post(
                f"/pin/{correction_id}",
                json={
                    "lawyer_id": "Partner A",
                    "actor_tier": "FirmAuthoritative",
                    "reason": "Firm position confirmed through route wrapper",
                    "pinned_at": "2026-02-03T00:00:00+00:00",
                },
            )
            return {
                "created": created,
                "dependency": dependency,
                "suggested_item": suggested_item,
                "suggestions": suggestions,
                "suggest_rerun": suggest_rerun,
                "confirm_suggestion": confirm_suggestion,
                "rejected_item": rejected_item,
                "reject_suggestions": reject_suggestions,
                "reject_suggestion": reject_suggestion,
                "currency": currency,
                "plan": plan,
                "impact": impact,
                "graph": graph,
                "references": references,
                "prediction": prediction,
                "timeline": timeline,
                "contest": contest,
                "affirm": affirm,
                "pin": pin,
            }

    responses = asyncio.run(exercise())

    for name, response in responses.items():
        assert response.status_code == 200, name
    item_id = responses["created"].json()["id"]
    assert responses["dependency"].json()["source_id"] == item_id
    assert responses["suggestions"].json()[0]["decision"] == "pending"
    assert responses["suggest_rerun"].json() == []
    assert responses["confirm_suggestion"].json()["confidence"] == "human_confirmed"
    assert responses["reject_suggestion"].json()["decision"] == "rejected"
    assert responses["currency"].json()["currency_state"] == "Live"
    assert responses["plan"].json()["steps"][0]["primitive"] == "recall"
    assert responses["impact"].json()["stale_item_ids"] == [item_id]
    assert "reg-r-12" in responses["graph"].text
    assert responses["references"].json()["defined_terms"][0]["term"] == "Covered Structure"
    assert responses["prediction"].json()["risks"][0]["item_id"] == item_id
    assert responses["timeline"].json()[0]["item"]["id"] == item_id
    assert responses["contest"].json()["item"]["metadata"]["contested"] is True
    assert responses["affirm"].json()["superseded"] is True
    assert responses["pin"].json()["metadata"]["credence_floor"] == "FirmAuthoritative"


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


def test_server_tenant_registry_lifecycle_and_keys(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            sku="server",
            zero_egress_mode=False,
            data_dir=tmp_path / "data",
            journal_dir=tmp_path / "journal",
            server_api_key="admin-secret",
            server_auto_provision_tenants=False,
        )
    )
    admin_headers = {"x-api-key": "admin-secret"}
    tenant_headers = {"x-api-key": "tenant-secret", "x-tenant-id": "managed-tenant"}
    wrong_headers = {"x-api-key": "wrong-secret", "x-tenant-id": "managed-tenant"}
    payload = {
        "kind": "position",
        "content": "managed tenant position",
        "source_kind": "partner",
        "source_ref": "managed-memo",
    }

    async def exercise() -> tuple[
        httpx.Response,
        httpx.Response,
        httpx.Response,
        httpx.Response,
        httpx.Response,
        httpx.Response,
        httpx.Response,
        httpx.Response,
        httpx.Response,
    ]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            unknown_tenant = await client.post(
                "/recall",
                headers={"x-api-key": "admin-secret", "x-tenant-id": "managed-tenant"},
                json={"query": "managed tenant"},
            )
            created_tenant = await client.post(
                "/tenants",
                headers=admin_headers,
                json={
                    "tenant_id": "managed-tenant",
                    "display_name": "Managed Tenant",
                    "api_key": "tenant-secret",
                },
            )
            listed_tenants = await client.get("/tenants", headers=admin_headers)
            rejected = await client.post("/ingest", headers=wrong_headers, json=payload)
            created_item = await client.post("/ingest", headers=tenant_headers, json=payload)
            suspended = await client.post("/tenants/managed-tenant/suspend", headers=admin_headers)
            suspended_recall = await client.post(
                "/recall",
                headers=tenant_headers,
                json={"query": "managed tenant", "review_mode": True},
            )
            reactivated = await client.post("/tenants/managed-tenant/reactivate", headers=admin_headers)
            tenant_recall = await client.post(
                "/recall",
                headers=tenant_headers,
                json={"query": "managed tenant", "review_mode": True},
            )
            return (
                unknown_tenant,
                created_tenant,
                listed_tenants,
                rejected,
                created_item,
                suspended,
                suspended_recall,
                reactivated,
                tenant_recall,
            )

    (
        unknown_tenant,
        created_tenant,
        listed_tenants,
        rejected,
        created_item,
        suspended,
        suspended_recall,
        reactivated,
        tenant_recall,
    ) = asyncio.run(exercise())

    assert unknown_tenant.status_code == 404
    assert created_tenant.status_code == 201
    assert created_tenant.json()["api_key_configured"] is True
    assert created_tenant.json()["status"] == "active"
    assert listed_tenants.json()[0]["tenant_id"] == "managed-tenant"
    assert rejected.status_code == 401
    assert created_item.status_code == 200
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"
    assert suspended_recall.status_code == 403
    assert reactivated.status_code == 200
    assert reactivated.json()["status"] == "active"
    assert len(tenant_recall.json()) == 1
    raw_registry = (tmp_path / "data" / "tenants" / "registry.json").read_text(encoding="utf-8")
    assert "tenant-secret" not in raw_registry
    assert "pbkdf2_sha256" in raw_registry


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


def test_sync_client_preserves_error_status_code() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    with SolomonClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SolomonAPIError) as exc_info:
            client.recall({"query": "x"})

    assert exc_info.value.status_code == 403
    assert str(exc_info.value) == "forbidden"


def test_async_client_uses_httpx_transport_and_preserves_errors() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ingest":
            payload: dict[str, Any] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"id": "item-1", **payload})
        if request.url.path == "/recall":
            return httpx.Response(200, json=[{"item": {"id": "item-1"}}])
        if request.url.path == "/why/item-1":
            return httpx.Response(200, json={"item": {"id": "item-1"}})
        return httpx.Response(409, text="conflict")

    async def exercise() -> None:
        async with AsyncSolomonClient(transport=httpx.MockTransport(handler)) as client:
            assert (await client.ingest({"content": "x"}))["id"] == "item-1"
            assert (await client.recall({"query": "x"}))[0]["item"]["id"] == "item-1"
            assert (await client.why("item-1"))["item"]["id"] == "item-1"
            with pytest.raises(SolomonAPIError) as exc_info:
                await client.why("missing")
            assert exc_info.value.status_code == 409
            assert str(exc_info.value) == "conflict"

    asyncio.run(exercise())
