# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import httpx

from solomon.api.app import create_app
from solomon.config import local_settings, server_settings


def test_metrics_exposes_health_queue_sync_delivery_retrieval_and_withholding(tmp_path: Path) -> None:
    app = create_app(settings=local_settings(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal"))

    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            source = await client.post(
                "/sources",
                json={"name": "knowledge", "kind": "filesystem", "root_ref": "/knowledge"},
            )
            item = await client.post(
                "/ingest",
                json={
                    "kind": "house-view",
                    "content": "Structure X depends on Regulation R section 12.",
                    "source_kind": "partner",
                    "source_ref": "memo-1",
                },
            )
            dependency = await client.post(
                "/dependencies",
                json={
                    "source_id": item.json()["id"],
                    "target_id": "reg-r-12",
                    "edge_type": "internal_depends_on_external",
                    "target_kind": "external_authority",
                },
            )
            authority_event = await client.post(
                "/authority-events",
                json={
                    "source_id": "feed-a",
                    "idempotency_key": "event-a",
                    "authority_id": "reg-r-12",
                    "new_version": "v2",
                    "changed_at": "2026-07-13T00:00:00Z",
                },
            )
            recall = await client.post("/recall", json={"query": "Structure X Regulation R"})
            assert source.status_code == 200
            assert item.status_code == 200
            assert dependency.status_code == 200
            assert authority_event.status_code == 200
            assert recall.status_code == 200
            assert recall.json() == []
            return await client.get("/metrics")

    response = asyncio.run(exercise())

    assert response.headers["content-type"].startswith("text/plain; version=")
    metrics = response.text
    assert 'solomon_health{component="audit_journal"} 1.0' in metrics
    assert re.search(r'solomon_queue_depth\{queue="knowledge_outbox"\} [1-9][0-9]*\.0', metrics)
    assert 'solomon_queue_depth{queue="authority_poll_dead_letter"} 0.0' in metrics
    assert 'solomon_review_tasks{state="open"} 1.0' in metrics
    assert 'solomon_source_sync_sources{state="never"} 1.0' in metrics
    assert "solomon_http_request_duration_seconds_bucket" in metrics
    assert "solomon_metrics_scrape_duration_seconds_bucket" in metrics
    assert "solomon_retrieval_requests_total 1.0" in metrics
    assert "solomon_retrieval_candidates_total 1.0" in metrics
    assert "solomon_retrieval_results_total 0.0" in metrics
    assert 'solomon_retrieval_context_withheld_total{currency_state="StalePendingReverification"} 1.0' in metrics


def test_metrics_is_public_in_server_sku(tmp_path: Path) -> None:
    app = create_app(settings=server_settings(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal"))

    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get("/metrics")

    response = asyncio.run(exercise())

    assert response.status_code == 200
    assert "solomon_health" in response.text
