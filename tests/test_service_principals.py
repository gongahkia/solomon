# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from solomon.api.app import create_app
from solomon.api.service_principals import ServicePrincipalRegistry
from solomon.config import Settings


def test_service_principal_lifecycle_enforces_scope_tenant_rotation_and_revocation(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            sku="server",
            zero_egress_mode=False,
            data_dir=tmp_path / "data",
            journal_dir=tmp_path / "journal",
            server_api_key="admin-secret",
            server_auth_mode="legacy-api-key",
            server_auto_provision_tenants=False,
        )
    )
    admin_headers = {"x-api-key": "admin-secret", "x-correlation-id": "service-principal-admin"}

    async def exercise() -> dict[str, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            for tenant_id in ("connector-a", "connector-b"):
                response = await client.post("/tenants", headers=admin_headers, json={"tenant_id": tenant_id})
                assert response.status_code == 201
            created = await client.post(
                "/service-principals",
                headers=admin_headers,
                json={
                    "principal_id": "document-connector",
                    "tenant_id": "connector-a",
                    "scopes": ["tenant:read"],
                },
            )
            credential = created.json()["credential"]
            duplicate = await client.post(
                "/service-principals",
                headers=admin_headers,
                json={
                    "principal_id": "document-connector",
                    "tenant_id": "connector-a",
                    "scopes": ["tenant:read"],
                },
            )
            listed = await client.get("/service-principals", headers=admin_headers)
            principal_headers = {
                "x-api-key": credential,
                "x-tenant-id": "connector-a",
                "x-correlation-id": "service-principal-access",
            }
            allowed_recall = await client.post(
                "/recall",
                headers=principal_headers,
                json={"query": "connector"},
            )
            denied_ingest = await client.post(
                "/ingest",
                headers=principal_headers,
                json={
                    "kind": "position",
                    "content": "connector cannot write",
                    "source_kind": "partner",
                    "source_ref": "connector-test",
                },
            )
            wrong_tenant = await client.post(
                "/recall",
                headers={"x-api-key": credential, "x-tenant-id": "connector-b"},
                json={"query": "connector"},
            )
            rotated = await client.post("/service-principals/document-connector/rotate", headers=admin_headers)
            rotated_credential = rotated.json()["credential"]
            old_credential = await client.post(
                "/recall",
                headers={"x-api-key": credential, "x-tenant-id": "connector-a"},
                json={"query": "connector"},
            )
            new_credential = await client.post(
                "/recall",
                headers={
                    "x-api-key": rotated_credential,
                    "x-tenant-id": "connector-a",
                    "x-correlation-id": "service-principal-access",
                },
                json={"query": "connector"},
            )
            revoked = await client.post("/service-principals/document-connector/revoke", headers=admin_headers)
            revoked_credential = await client.post(
                "/recall",
                headers={"x-api-key": rotated_credential, "x-tenant-id": "connector-a"},
                json={"query": "connector"},
            )
        return {
            "created": created,
            "duplicate": duplicate,
            "listed": listed,
            "allowed_recall": allowed_recall,
            "denied_ingest": denied_ingest,
            "wrong_tenant": wrong_tenant,
            "rotated": rotated,
            "old_credential": old_credential,
            "new_credential": new_credential,
            "revoked": revoked,
            "revoked_credential": revoked_credential,
        }

    responses = asyncio.run(exercise())

    assert responses["created"].status_code == 201
    assert responses["created"].json()["credential"].startswith("solomon_sp_")
    assert responses["duplicate"].status_code == 409
    assert responses["listed"].status_code == 200
    assert responses["listed"].json() == [
        {
            "principal_id": "document-connector",
            "tenant_id": "connector-a",
            "status": "active",
            "created_at": responses["created"].json()["created_at"],
            "updated_at": responses["created"].json()["updated_at"],
            "scopes": ["tenant:read"],
        }
    ]
    assert responses["allowed_recall"].status_code == 200
    assert responses["denied_ingest"].status_code == 403
    assert responses["wrong_tenant"].status_code == 401
    assert responses["rotated"].status_code == 200
    assert responses["rotated"].json()["credential"] != responses["created"].json()["credential"]
    assert responses["old_credential"].status_code == 401
    assert responses["new_credential"].status_code == 200
    assert responses["revoked"].status_code == 200
    assert responses["revoked"].json()["status"] == "revoked"
    assert responses["revoked_credential"].status_code == 401

    stored = (tmp_path / "data" / "service-principals" / "registry.json").read_text(encoding="utf-8")
    assert "key_hash" in stored
    assert responses["created"].json()["credential"] not in stored
    assert responses["rotated"].json()["credential"] not in stored

    lifecycle = [
        entry
        for entry in app.state.service.audit.list_entries(correlation_id="service-principal-admin")
        if entry.event_type == "service_principal_lifecycle"
    ]
    assert [entry.payload["decision"] for entry in lifecycle] == ["created", "rotated", "revoked"]
    assert all(entry.attribution and entry.attribution.actor_id == "server-admin" for entry in lifecycle)
    access = [
        entry
        for entry in app.state.service.audit.list_entries(actor_id="service-principal:document-connector")
        if entry.event_type == "service_principal_authentication"
    ]
    assert [entry.payload["decision"] for entry in access] == ["allowed", "denied", "allowed"]
    assert all(entry.attribution and entry.attribution.correlation_id == "service-principal-access" for entry in access)


def test_service_principal_registry_hashes_credentials_and_rejects_invalid_ids(tmp_path: Path) -> None:
    registry = ServicePrincipalRegistry(tmp_path / "registry.json")
    record, credential = registry.create(
        principal_id="connector-1",
        tenant_id="tenant-a",
        scopes=["tenant:read"],
    )

    assert registry.authenticate(tenant_id="tenant-a", credential=credential) == record
    assert registry.authenticate(tenant_id="tenant-b", credential=credential) is None
    assert credential not in registry.path.read_text(encoding="utf-8")

    try:
        registry.create(principal_id="x", tenant_id="tenant-a")
    except ValueError as exc:
        assert str(exc) == "invalid service principal id"
    else:
        raise AssertionError("invalid service principal ID accepted")
