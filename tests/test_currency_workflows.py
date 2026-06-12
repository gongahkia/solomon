# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from solomon.currency.feeds import apply_authority_changes, load_authority_changes, poll_authority_change_feed
from solomon.currency.models import KnowledgeItem, KnowledgeKind, Provenance, SourceKind
from solomon.currency.prediction import AuthorityChangeHistory, load_pending_amendments, predict_staleness_risk
from solomon.currency.report import currency_report
from solomon.currency.supersession import confirm_supersession, propose_supersession
from solomon.graph.models import DependencyEdge, EdgeType
from solomon.graph.store import GraphStore
from solomon.store.sqlite import SQLiteKnowledgeStore


def _dt(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


def _item(item_id: str, content: str, year: int) -> KnowledgeItem:
    return KnowledgeItem(
        id=item_id,
        kind=KnowledgeKind.POSITION,
        content=content,
        provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref=item_id),
        valid_from=_dt(year),
        ingested_at=_dt(year),
        matter_id="matter-a",
        metadata={"topic": "structure-x", "jurisdiction": "SG"},
    )


def test_supersession_proposal_and_confirmation(tmp_path: Path) -> None:
    store = SQLiteKnowledgeStore(tmp_path / "solomon.sqlite3")
    old = _item("old", "old view", 2023)
    new = _item("new", "new contradictory view", 2025).model_copy(
        update={"metadata": {"topic": "structure-x", "jurisdiction": "SG", "contradicts": "old"}}
    )
    store.write_item(old)
    store.write_item(new)

    proposal = propose_supersession(new, [old])[0]
    closed, successor = confirm_supersession(store, proposal)

    assert proposal.requires_human_confirmation is True
    assert closed.successor_id == "new"
    assert successor.metadata["supersedes"] == "old"


def test_authority_json_feed_and_currency_report(tmp_path: Path) -> None:
    db = tmp_path / "solomon.sqlite3"
    store = SQLiteKnowledgeStore(db)
    graph = GraphStore(db)
    item = _item("item-1", "view under regulation", 2023)
    store.write_item(item)
    graph.add_dependency(
        DependencyEdge(
            source_id="item-1",
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )
    feed = tmp_path / "feed.json"
    feed.write_text(
        json.dumps(
            {
                "changes": [
                    {
                        "authority_id": "reg-r-12",
                        "new_version": "2025",
                        "changed_at": "2025-01-01T00:00:00+00:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    impacts = apply_authority_changes(load_authority_changes(feed), graph=graph, store=store)
    report = currency_report(store=store, graph=graph, matter_id="matter-a")

    assert impacts[0].stale_item_ids == ["item-1"]
    assert report.items[0]["item_id"] == "item-1"
    assert report.items[0]["dependencies"][0]["target_id"] == "reg-r-12"


def test_http_authority_feed_monitor_uses_conditional_requests() -> None:
    seen_headers: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(dict(request.headers))
        if len(seen_headers) == 1:
            return httpx.Response(
                200,
                headers={"ETag": '"feed-v1"', "Last-Modified": "Fri, 12 Jun 2026 00:00:00 GMT"},
                json={
                    "changes": [
                        {
                            "authority_id": "reg-r-12",
                            "new_version": "2026",
                            "changed_at": "2026-06-12T00:00:00+00:00",
                        }
                    ]
                },
            )
        return httpx.Response(304)

    transport = httpx.MockTransport(handler)

    first = poll_authority_change_feed("https://regulator.example/feed.json", transport=transport)
    second = poll_authority_change_feed(
        "https://regulator.example/feed.json",
        state=first.state,
        transport=transport,
    )

    assert first.changed is True
    assert first.changes[0].authority_id == "reg-r-12"
    assert first.state.etag == '"feed-v1"'
    assert second.changed is False
    assert second.changes == []
    assert seen_headers[1]["if-none-match"] == '"feed-v1"'
    assert seen_headers[1]["if-modified-since"] == "Fri, 12 Jun 2026 00:00:00 GMT"


def test_pending_amendment_predicts_transitive_staleness_risk(tmp_path: Path) -> None:
    db = tmp_path / "solomon.sqlite3"
    store = SQLiteKnowledgeStore(db)
    graph = GraphStore(db)
    store.write_item(_item("item-1", "direct dependency", 2023))
    store.write_item(_item("item-2", "relies on item 1", 2023))
    graph.add_dependency(
        DependencyEdge(
            id="edge-ext",
            source_id="item-1",
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )
    graph.add_dependency(
        DependencyEdge(
            id="edge-internal",
            source_id="item-2",
            target_id="item-1",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_INTERNAL,
            target_kind="knowledge_item",
        )
    )
    feed = tmp_path / "pending.json"
    feed.write_text(
        json.dumps(
            {
                "pending_amendments": [
                    {
                        "authority_id": "reg-r-12",
                        "expected_change_at": "2024-01-20T00:00:00+00:00",
                        "description": "consultation closes and amendment is expected",
                        "source_ref": "regulator-update",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = predict_staleness_risk(
        load_pending_amendments(feed),
        graph=graph,
        store=store,
        as_of=_dt(2024),
        lookahead_days=60,
    )

    assert [risk.item_id for risk in report.risks] == ["item-1", "item-2"]
    assert {risk.risk_level for risk in report.risks} == {"high"}
    assert report.risks[1].dependency_path == ["edge-ext", "edge-internal"]


def test_staleness_forecast_uses_authority_change_history(tmp_path: Path) -> None:
    db = tmp_path / "solomon.sqlite3"
    store = SQLiteKnowledgeStore(db)
    graph = GraphStore(db)
    store.write_item(_item("item-1", "direct dependency", 2023))
    graph.add_dependency(
        DependencyEdge(
            source_id="item-1",
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )
    amendment = load_pending_amendments(
        tmp_path / "pending.json"
        if (tmp_path / "pending.json").exists()
        else _write_pending_feed(tmp_path / "pending.json")
    )

    without_history = predict_staleness_risk(amendment, graph=graph, store=store, as_of=_dt(2024), lookahead_days=60)
    with_history = predict_staleness_risk(
        amendment,
        graph=graph,
        store=store,
        history=[
            AuthorityChangeHistory(authority_id="reg-r-12", changed_at=_dt(2023)),
            AuthorityChangeHistory(authority_id="reg-r-12", changed_at=datetime(2023, 6, 1, tzinfo=timezone.utc)),
        ],
        as_of=_dt(2024),
        lookahead_days=60,
    )

    assert with_history.risks[0].historical_change_count == 2
    assert with_history.risks[0].forecast_score > without_history.risks[0].forecast_score
    assert "2 prior changes" in with_history.risks[0].reason


def _write_pending_feed(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "pending_amendments": [
                    {
                        "authority_id": "reg-r-12",
                        "expected_change_at": "2024-01-20T00:00:00+00:00",
                        "description": "consultation closes and amendment is expected",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path
