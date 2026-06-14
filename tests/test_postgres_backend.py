# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from solomon.currency.models import CredenceTier, CurrencyState, KnowledgeItem, KnowledgeKind, Provenance, SourceKind
from solomon.graph.models import DependencyEdge, EdgeType
from solomon.graph.propagation import CurrencyPropagator
from solomon.graph.suggestions import DependencySuggestion, SuggestionDecision
from solomon.orchestrator.retrieval import MatterContext, RecallOptions, RetrievalOrchestrator
from solomon.store.factory import create_storage_bundle
from solomon.store.postgres import PostgresGraphStore, PostgresKnowledgeStore, PostgresRetrievalIndex
from tests.postgres_fake import FakePostgresConnection


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _item(item_id: str, content: str, ingested_at: datetime | None = None) -> KnowledgeItem:
    timestamp = ingested_at or _dt(2024, 1, 1)
    return KnowledgeItem(
        id=item_id,
        kind=KnowledgeKind.POSITION,
        content=content,
        provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref=f"{item_id}.md"),
        valid_from=timestamp,
        ingested_at=timestamp,
        credence_tier=CredenceTier.FIRM_AUTHORITATIVE,
        last_verified_at=timestamp,
        verified_by="Partner A",
    )


def _connect(tmp_path: Path) -> FakePostgresConnection:
    return FakePostgresConnection(tmp_path / "postgres.sqlite3")


def test_postgres_knowledge_store_preserves_append_only_store_semantics(tmp_path: Path) -> None:
    store = PostgresKnowledgeStore("postgresql://unit/solomon", connect=lambda _dsn: _connect(tmp_path))
    predecessor = _item("item-1", "2023 house view", _dt(2023, 1, 1))
    successor = _item("item-2", "2025 replacement view", _dt(2025, 1, 1))

    store.write_item(predecessor)
    closed, written_successor = store.supersede("item-1", successor, superseded_at=_dt(2025, 1, 1))

    assert closed.currency_state is CurrencyState.SUPERSEDED
    assert store.get_item("item-1").successor_id == "item-2"
    assert {item.id for item in store.get_many()} == {"item-1", "item-2"}
    assert store.get_many(include_states={CurrencyState.LIVE}) == [written_successor]
    assert [(item.id, item.currency_state) for item in store.as_of(_dt(2024, 1, 1))] == [
        ("item-1", CurrencyState.LIVE)
    ]

    snapshot = store.snapshot(tmp_path / "snapshot.json")
    restored = PostgresKnowledgeStore.restore(
        snapshot,
        "postgresql://unit/restored",
        connect=lambda _dsn: FakePostgresConnection(tmp_path / "restored.sqlite3"),
    )
    assert restored.get_item("item-2").metadata["supersedes"] == "item-1"


def test_postgres_graph_index_and_retrieval_match_sqlite_workflow(tmp_path: Path) -> None:
    dsn = "postgresql://unit/solomon"

    def connect(_dsn: str) -> FakePostgresConnection:
        return _connect(tmp_path)

    store = PostgresKnowledgeStore(dsn, connect=connect)
    graph = PostgresGraphStore(dsn, connect=connect)
    index = PostgresRetrievalIndex(dsn, connect=connect)
    orchestrator = RetrievalOrchestrator(store=store, graph=graph, index=index)
    item = _item("item-1", "structure x under regulation r section 12")
    store.write_item(item)
    orchestrator.index_items([item])
    graph.add_dependency(
        DependencyEdge(
            id="edge-1",
            source_id="item-1",
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
            created_at=_dt(2024, 1, 1),
            valid_from=_dt(2024, 1, 1),
        )
    )

    recall = orchestrator.recall(
        "structure regulation",
        matter_context=MatterContext(),
        options=RecallOptions(review_mode=True),
    )
    impact = CurrencyPropagator(graph=graph, store=store).propagate_dependency_change(
        "reg-r-12",
        changed_at=_dt(2025, 1, 1),
        reason="Regulation R section 12 amended",
    )

    assert recall[0].item.id == "item-1"
    assert impact.stale_item_ids == ["item-1"]
    assert store.get_item("item-1").currency_state is CurrencyState.STALE_PENDING_REVERIFICATION


def test_postgres_graph_store_persists_dependency_suggestions(tmp_path: Path) -> None:
    graph = PostgresGraphStore("postgresql://unit/solomon", connect=lambda _dsn: _connect(tmp_path))
    suggestion = DependencySuggestion(
        id="suggestion-1",
        item_id="item-1",
        authority_ref="Regulation R section 12",
        suggested_edge=DependencyEdge(
            id="edge-suggested",
            source_id="item-1",
            target_id="regulation-r-section-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        ),
    )

    graph.add_dependency_suggestion(suggestion)
    rejected = suggestion.model_copy(update={"decision": SuggestionDecision.REJECTED, "decided_by": "Partner A"})
    graph.update_dependency_suggestion(rejected)

    assert graph.get_dependency_suggestion("suggestion-1").decision is SuggestionDecision.REJECTED
    assert graph.list_dependency_suggestions(item_id="item-1", decision=SuggestionDecision.REJECTED) == [rejected]


def test_storage_bundle_can_create_postgres_store_graph_and_index(tmp_path: Path) -> None:
    bundle = create_storage_bundle(
        "postgresql://unit/solomon",
        postgres_connect=lambda _dsn: _connect(tmp_path),
        postgres_schema="tenant-a",
    )

    item = _item("item-1", "tenant scoped position")
    indexed = bundle.index.upsert_item(item)
    bundle.store.write_item(indexed)

    assert bundle.store.get_item("item-1").embedding_ref == bundle.index.strategy.ref
