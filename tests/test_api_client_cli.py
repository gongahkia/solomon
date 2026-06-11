# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from solomon.api.app import create_app
from solomon.api.service import IngestRequest, RecallRequest, SolomonService
from solomon.client import SolomonClient
from solomon.config import Settings
from solomon.currency.models import KnowledgeKind, SourceKind


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
