# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from solomon.currency.models import (
    CredenceTier,
    CurrencyState,
    KnowledgeItem,
    KnowledgeKind,
    Provenance,
    SourceKind,
)
from solomon.graph.models import DependencyEdge, EdgeConfidence, EdgeType
from solomon.graph.propagation import CurrencyPropagator
from solomon.graph.store import GraphStore
from solomon.graph.visualization import dependency_graph_view, render_dependency_graph
from solomon.store.sqlite import SQLiteKnowledgeStore


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _item(item_id: str, content: str) -> KnowledgeItem:
    return KnowledgeItem(
        id=item_id,
        kind=KnowledgeKind.POSITION,
        content=content,
        provenance=Provenance(source_kind=SourceKind.ASSOCIATE, source_ref=f"{item_id}.md"),
        valid_from=_dt(2023, 1, 1),
        ingested_at=_dt(2023, 1, 1),
        credence_tier=CredenceTier.VERIFIED,
    )


def _scoped_item(item_id: str, content: str, *, matter_id: str) -> KnowledgeItem:
    return _item(item_id, content).model_copy(update={"matter_id": matter_id})


def _external_edge(source: str, target: str, *, edge_id: str = "edge-1") -> DependencyEdge:
    return DependencyEdge(
        id=edge_id,
        source_id=source,
        target_id=target,
        edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
        target_kind="external_authority",
        valid_from=_dt(2023, 1, 1),
        created_at=_dt(2023, 1, 1),
        confidence=EdgeConfidence.HUMAN_ASSERTED,
    )


def _internal_edge(source: str, target: str, *, edge_id: str) -> DependencyEdge:
    return DependencyEdge(
        id=edge_id,
        source_id=source,
        target_id=target,
        edge_type=EdgeType.INTERNAL_DEPENDS_ON_INTERNAL,
        target_kind="knowledge_item",
        valid_from=_dt(2023, 1, 1),
        created_at=_dt(2023, 1, 1),
        confidence=EdgeConfidence.LLM_SUGGESTED,
    )


def test_add_dependency_and_bitemporal_reads(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path / "solomon.sqlite3")
    edge = _external_edge("item-1", "reg-r-12")

    graph.add_dependency(edge)
    graph.close_dependency("edge-1", valid_to=_dt(2025, 1, 1))

    assert graph.get_dependencies("item-1", at=_dt(2024, 1, 1))[0].id == "edge-1"
    assert graph.get_dependencies("item-1", at=_dt(2026, 1, 1)) == []
    assert graph.get_dependents("reg-r-12") == []


def test_propagation_flags_transitive_dependents_with_cycle_protection(tmp_path: Path) -> None:
    db = tmp_path / "solomon.sqlite3"
    store = SQLiteKnowledgeStore(db)
    graph = GraphStore(db)
    for item_id in ["item-1", "item-2", "item-3"]:
        store.write_item(_item(item_id, item_id))
    graph.add_dependency(_external_edge("item-1", "reg-r-12", edge_id="edge-ext"))
    graph.add_dependency(_internal_edge("item-2", "item-1", edge_id="edge-2-1"))
    graph.add_dependency(_internal_edge("item-3", "item-2", edge_id="edge-3-2"))
    graph.add_dependency(_internal_edge("item-1", "item-3", edge_id="edge-cycle"))

    result = CurrencyPropagator(graph=graph, store=store).propagate_dependency_change(
        "reg-r-12",
        changed_at=_dt(2025, 1, 1),
        reason="Regulation R section 12 amended",
    )

    assert result.stale_item_ids == ["item-1", "item-2", "item-3"]
    assert store.get_item("item-1").currency_state is CurrencyState.STALE_PENDING_REVERIFICATION
    assert store.get_item("item-2").metadata["staleness_reasons"][0]["dependency_id"] == "item-1"
    assert store.get_item("item-3").metadata["staleness_reasons"][0]["dependency_id"] == "item-2"


def test_impact_query_centrality_and_subgraph(tmp_path: Path) -> None:
    db = tmp_path / "solomon.sqlite3"
    store = SQLiteKnowledgeStore(db)
    graph = GraphStore(db)
    store.write_item(_item("item-1", "depends on R12"))
    store.write_item(_item("item-2", "also depends on R12"))
    edge1 = _external_edge("item-1", "reg-r-12", edge_id="edge-1")
    edge2 = _external_edge("item-2", "reg-r-12", edge_id="edge-2")
    graph.add_dependency(edge1)
    graph.add_dependency(edge2)

    impact = CurrencyPropagator(graph=graph, store=store).impact_query("reg-r-12")

    assert impact.stale_item_ids == ["item-1", "item-2"]
    assert graph.centrality()["reg-r-12"] == 2
    assert {edge.id for edge in graph.subgraph_for_items(["item-1"])} == {"edge-1"}
    assert graph.get_edge("edge-2").confidence is EdgeConfidence.HUMAN_ASSERTED


def test_subgraph_for_matter_scope(tmp_path: Path) -> None:
    db = tmp_path / "solomon.sqlite3"
    store = SQLiteKnowledgeStore(db)
    graph = GraphStore(db)
    store.write_item(_scoped_item("item-1", "matter a", matter_id="matter-a"))
    store.write_item(_scoped_item("item-2", "matter b", matter_id="matter-b"))
    graph.add_dependency(_external_edge("item-1", "reg-r-12", edge_id="edge-a"))
    graph.add_dependency(_external_edge("item-2", "reg-r-12", edge_id="edge-b"))

    scoped = graph.subgraph_for_scope(store=store, matter_id="matter-a")

    assert [edge.id for edge in scoped] == ["edge-a"]


def test_dependency_graph_visualization_renders_authorities_pointing_to_internal_knowledge(tmp_path: Path) -> None:
    db = tmp_path / "solomon.sqlite3"
    store = SQLiteKnowledgeStore(db)
    graph = GraphStore(db)
    store.write_item(_item("item-1", "House view under Regulation R section 12"))
    graph.add_dependency(_external_edge("item-1", "reg-r-12", edge_id="edge-1"))

    view = dependency_graph_view(graph=graph, store=store)
    mermaid = render_dependency_graph(view, output_format="mermaid")
    dot = render_dependency_graph(view, output_format="dot")

    assert 'authority_reg_r_12["reg-r-12"]:::authority' in mermaid
    assert "authority_reg_r_12 -->|relied on by| item_item_1" in mermaid
    assert '"external_authority:reg-r-12" -> "knowledge_item:item-1"' in dot
