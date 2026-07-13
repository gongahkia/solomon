# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from solomon.api.service import DocumentSourceRequest, SolomonService
from solomon.config import Settings
from solomon.console.app import create_console_app
from solomon.sources.models import DocumentExtractionState, DocumentSourceKind, SourceSyncRunState


def test_console_source_operations_syncs_and_retries_extraction(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    memo = root / "memo.txt"
    memo.write_text("", encoding="utf-8")
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    source = service.register_document_source(
        DocumentSourceRequest(name="knowledge", kind=DocumentSourceKind.FILESYSTEM, root_ref=str(root))
    )
    app = create_console_app(service=service)

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            initial = await client.get("/console/sources")
            synced = await client.post(f"/console/sources/{source.id}/sync")
            failed_document = service.document_store.list_latest_documents(source.id)[0]
            memo.write_text("Reusable proposition with enough source detail for review.", encoding="utf-8")
            retried = await client.post(
                f"/console/sources/{source.id}/documents/{failed_document.id}/retry-extraction"
            )
            return initial, synced, retried

    initial, synced, retried = asyncio.run(exercise())

    assert initial.status_code == 200
    assert source.name in initial.text
    assert synced.status_code == 200
    assert "document contains no extractable text" in synced.text
    assert retried.status_code == 200
    assert service.document_store.list_sync_runs(source.id)[0].state is SourceSyncRunState.SUCCEEDED
    assert service.document_store.list_latest_documents(source.id)[0].extraction_state is DocumentExtractionState.READY
    assert "document_source_synced" in [entry.event_type for entry in service.audit.list_entries()]
    assert "source_document_extraction_retried" in [entry.event_type for entry in service.audit.list_entries()]


def test_console_source_operations_rejects_unknown_source(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    app = create_console_app(service=service)

    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post("/console/sources/missing/sync")

    response = asyncio.run(call())

    assert response.status_code == 400
    assert "missing" in response.text


def test_console_source_operations_records_failed_sync_run(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    source = service.register_document_source(
        DocumentSourceRequest(
            name="missing-root",
            kind=DocumentSourceKind.FILESYSTEM,
            root_ref=str(tmp_path / "missing"),
        )
    )
    app = create_console_app(service=service)

    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(f"/console/sources/{source.id}/sync")

    response = asyncio.run(call())

    assert response.status_code == 400
    assert service.document_store.list_sync_runs(source.id)[0].state is SourceSyncRunState.FAILED
    assert "filesystem source root is not a readable directory" in response.text


def test_console_source_operations_requires_configured_bearer_token(tmp_path: Path) -> None:
    configured_value = "console-secret"
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    settings = Settings(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        console_bearer_token=configured_value,
    )
    app = create_console_app(settings=settings, service=service)

    async def call() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            denied = await client.get("/console/sources")
            allowed = await client.get("/console/sources", headers={"Authorization": f"Bearer {configured_value}"})
            return denied, allowed

    denied, allowed = asyncio.run(call())

    assert denied.status_code == 401
    assert allowed.status_code == 200
