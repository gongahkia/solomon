# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio

import httpx

from solomon.api.app import create_app
from solomon.config import local_settings


def test_source_claim_and_review_task_routes(tmp_path):
    app = create_app(settings=local_settings(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal"))

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            source = await client.post(
                "/sources",
                json={"name": "shared folder", "kind": "filesystem", "root_ref": "/knowledge"},
            )
            source_id = source.json()["id"]
            document = await client.post(
                f"/sources/{source_id}/documents",
                json={
                    "external_id": "memo-1",
                    "filename": "memo.txt",
                    "content": (
                        "First reusable proposition about Structure X.\n\nSecond proposition requires human review."
                    ),
                },
            )
            document_id = document.json()["document"]["id"]
            candidates = document.json()["candidate_claims"]
            listed = await client.get(f"/sources/{source_id}/documents")
            candidate_list = await client.get(f"/source-documents/{document_id}/candidates")
            promoted = await client.post(f"/candidate-claims/{candidates[0]['id']}/promote", json={"by": "curator-a"})
            rejected = await client.post(
                f"/candidate-claims/{candidates[1]['id']}/reject",
                json={"by": "curator-a", "reason": "not reusable"},
            )
            item = (
                await client.post(
                    "/ingest",
                    json={
                        "kind": "house-view",
                        "content": "Structure X depends on Regulation R section 12.",
                        "source_kind": "partner",
                        "source_ref": "memo-2",
                    },
                )
            ).json()
            dependency = await client.post(
                "/dependencies",
                json={
                    "source_id": item["id"],
                    "target_id": "reg-r-12",
                    "edge_type": "internal_depends_on_external",
                    "target_kind": "external_authority",
                },
            )
            event = await client.post(
                "/authority-events",
                json={
                    "source_id": "feed-a",
                    "idempotency_key": "event-a",
                    "authority_id": "reg-r-12",
                    "new_version": "v2",
                    "changed_at": "2026-07-13T00:00:00Z",
                },
            )
            task_id = event.json()["review_tasks"][0]["id"]
            tasks = await client.get("/review-tasks", params={"state": "open"})
            assigned = await client.post(
                f"/review-tasks/{task_id}/assign",
                json={"reviewer_id": "lawyer-a", "assigned_by": "curator-a"},
            )
            started = await client.post(f"/review-tasks/{task_id}/start", json={"reviewer_id": "lawyer-a"})
            resolved = await client.post(
                f"/review-tasks/{task_id}/resolve",
                json={
                    "reviewer_id": "lawyer-a",
                    "verification": {
                        "by": "lawyer-a",
                        "outcome": "reaffirm",
                        "basis": "official source reviewed",
                        "source_ref": "source://reg-r-12/v2",
                    },
                },
            )
            assert source.status_code == 200
            assert len(candidates) == 2
            assert listed.json()[0]["id"] == document_id
            assert candidate_list.status_code == 200
            assert promoted.status_code == 200
            assert rejected.status_code == 200
            assert dependency.status_code == 200
            assert event.status_code == 200
            assert tasks.json()[0]["id"] == task_id
            assert assigned.status_code == 200
            assert started.status_code == 200
            return source, document, event, resolved

    source, document, event, resolved = asyncio.run(exercise())
    assert source.status_code == 200
    assert document.status_code == 200
    assert event.status_code == 200
    assert resolved.json()["state"] == "resolved"
