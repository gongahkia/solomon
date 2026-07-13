# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio

import httpx
import pytest

from solomon.api.app import create_app
from solomon.api.service import DocumentSourceRequest, SolomonService
from solomon.config import Settings
from solomon.sources.models import DocumentSource, DocumentSourceKind


def test_source_registration_validates_roots_and_reuses_caller_source_id(tmp_path):
    with pytest.raises(ValueError, match="absolute path"):
        DocumentSource(name="relative", kind=DocumentSourceKind.FILESYSTEM, root_ref="knowledge")
    with pytest.raises(ValueError, match="Microsoft Graph"):
        DocumentSource(name="wrong graph", kind=DocumentSourceKind.MICROSOFT_GRAPH, root_ref="https://example.test/v1.0/sites")

    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    request = DocumentSourceRequest(
        source_id="filesystem-1",
        name="files",
        kind=DocumentSourceKind.FILESYSTEM,
        root_ref="/knowledge",
    )

    first = service.register_document_source(request)
    second = service.register_document_source(request)

    assert first == second
    assert service.document_store.list_sources() == [first]


def test_source_registration_requires_source_manage_scope(tmp_path):
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
    admin_headers = {"Authorization": "Bearer admin-secret"}
    writer_headers = {"Authorization": "Bearer writer-secret", "x-tenant-id": "writer"}
    manager_headers = {"Authorization": "Bearer manager-secret", "x-tenant-id": "manager"}

    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            for tenant_id, key, scopes in (
                ("writer", "writer-secret", ["tenant:write"]),
                ("manager", "manager-secret", ["source:manage"]),
            ):
                response = await client.post(
                    "/tenants",
                    headers=admin_headers,
                    json={"tenant_id": tenant_id, "api_key": key, "api_key_scopes": scopes},
                )
                assert response.status_code == 201
            payload = {"source_id": "filesystem-1", "name": "files", "kind": "filesystem", "root_ref": "/knowledge"}
            denied = await client.post("/sources", headers=writer_headers, json=payload)
            allowed = await client.post("/sources", headers=manager_headers, json=payload)
            return denied, allowed

    denied, allowed = asyncio.run(exercise())

    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"
    assert allowed.status_code == 200
    assert allowed.json()["id"] == "filesystem-1"
