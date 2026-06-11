# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from solomon.currency.feeds import apply_authority_changes, load_authority_changes
from solomon.currency.models import KnowledgeItem, KnowledgeKind, Provenance, SourceKind
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
