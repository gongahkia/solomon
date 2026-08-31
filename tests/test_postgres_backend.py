# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from solomon.currency.models import CredenceTier, CurrencyState, KnowledgeItem, KnowledgeKind, Provenance, SourceKind
from solomon.graph.models import DependencyEdge, EdgeType
from solomon.graph.propagation import CurrencyPropagator
from solomon.graph.suggestions import DependencySuggestion, SuggestionDecision
from solomon.orchestrator.retrieval import MatterContext, RecallOptions, RetrievalOrchestrator
from solomon.store.factory import create_storage_bundle
from solomon.store.postgres import (
    PostgresGraphStore,
    PostgresKnowledgeStore,
    PostgresRetrievalIndex,
    PostgresVectorExtensionError,
)
from solomon.store.postgres.connection import quote_identifier
from solomon.store.sqlite import StoreError
from tests.postgres_fake import FakePostgresConnection


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _item(
    item_id: str,
    content: str,
    ingested_at: datetime | None = None,
    *,
    matter_id: str | None = None,
    client_id: str | None = None,
) -> KnowledgeItem:
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
        matter_id=matter_id,
        client_id=client_id,
    )


def _connect(tmp_path: Path) -> FakePostgresConnection:
    return FakePostgresConnection(tmp_path / "postgres.sqlite3")


def test_postgres_identifier_quoting_rejects_sql_fragments() -> None:
    with pytest.raises(StoreError, match="invalid SQL identifier"):
        quote_identifier("retrieval_index; DROP TABLE knowledge_items; --")


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
    assert [(item.id, item.currency_state) for item in store.as_of(_dt(2024, 1, 1))] == [("item-1", CurrencyState.LIVE)]

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


def test_postgres_hybrid_candidates_filter_scope_before_fusion(tmp_path: Path) -> None:
    dsn = "postgresql://unit/solomon"
    store = PostgresKnowledgeStore(dsn, connect=lambda _dsn: _connect(tmp_path))
    graph = PostgresGraphStore(dsn, connect=lambda _dsn: _connect(tmp_path))
    index = PostgresRetrievalIndex(dsn, connect=lambda _dsn: _connect(tmp_path))
    in_scope = _item(
        "in-scope",
        "citadel priority clause",
        matter_id="matter-a",
        client_id="client-a",
    )
    out_of_scope = _item(
        "out-of-scope",
        "citadel priority clause",
        matter_id="matter-b",
        client_id="client-b",
    )
    store.write_item(in_scope)
    store.write_item(out_of_scope)
    index.batch_upsert([in_scope, out_of_scope])
    orchestrator = RetrievalOrchestrator(store=store, graph=graph, index=index)

    results = orchestrator.recall(
        "citadel priority clause",
        matter_context=MatterContext(matter_id="matter-a", client_id="client-a"),
        options=RecallOptions(review_mode=True, dedupe_near_identical=False),
    )

    assert [result.item.id for result in results] == ["in-scope"]
    assert results[0].score_explanation.semantic_rank == 1
    assert results[0].score_explanation.lexical_rank == 1


def test_postgres_graph_store_persists_dependency_suggestions(tmp_path: Path) -> None:
    graph = PostgresGraphStore("postgresql://unit/solomon", connect=lambda _dsn: _connect(tmp_path))
    suggestion = DependencySuggestion(
        id="suggestion-1",
        item_id="item-1",
        authority_ref="Regulation R section 12",
        fingerprint="fixture-fingerprint",
        normalized_reference="regulation-r-section-12",
        source_document_id="document-1",
        source_document_version=2,
        previous_source_document_id="document-0",
        source_span_start=10,
        source_span_end=42,
        source_span="The position relies on Regulation R section 12.",
        authority_span_start=34,
        authority_span_end=57,
        authority_span="Regulation R section 12",
        matter_id="matter-1",
        client_id="client-1",
        explanation="fixture evidence",
        audit_correlation_id="dependency_suggestion:item-1",
        suggested_edge=DependencyEdge(
            id="edge-suggested",
            source_id="item-1",
            target_id="regulation-r-section-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        ),
    )

    graph.add_dependency_suggestion(suggestion)
    deferred = suggestion.model_copy(
        update={
            "decision": SuggestionDecision.DEFERRED,
            "decided_by": "Partner A",
            "decided_at": _dt(2024, 1, 2),
            "decision_reason": "need surrounding context",
        }
    )
    graph.update_dependency_suggestion(deferred)

    graph.close()
    reopened = PostgresGraphStore("postgresql://unit/solomon", connect=lambda _dsn: _connect(tmp_path))
    persisted = reopened.get_dependency_suggestion("suggestion-1")
    assert persisted.decision is SuggestionDecision.DEFERRED
    assert persisted.fingerprint == "fixture-fingerprint"
    assert persisted.source_document_version == 2
    assert persisted.source_span == "The position relies on Regulation R section 12."
    assert persisted.matter_id == "matter-1"
    assert persisted.audit_correlation_id == "dependency_suggestion:item-1"
    assert reopened.list_dependency_suggestions(item_id="item-1", decision=SuggestionDecision.DEFERRED) == [deferred]

    rejected = deferred.model_copy(
        update={
            "decision": SuggestionDecision.REJECTED,
            "decided_at": _dt(2024, 1, 3),
            "decision_reason": "reviewed as non-reliance",
        }
    )
    reopened.update_dependency_suggestion(rejected)

    assert reopened.get_dependency_suggestion("suggestion-1").decision is SuggestionDecision.REJECTED
    assert reopened.list_dependency_suggestions(item_id="item-1", decision=SuggestionDecision.REJECTED) == [rejected]
    reopened.close()


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


def test_postgres_retrieval_migrates_legacy_vectors_and_dual_writes_embeddings(tmp_path: Path) -> None:
    connection = _connect(tmp_path)
    legacy_vector = json.dumps([0.0] * 256)
    connection.execute(
        """
        CREATE TABLE retrieval_index (
            item_id TEXT PRIMARY KEY,
            embedding_ref TEXT NOT NULL,
            tokens_json TEXT NOT NULL,
            vector_json TEXT NOT NULL,
            indexed_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO retrieval_index (item_id, embedding_ref, tokens_json, vector_json, indexed_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("legacy", "hashed-token-vector:1", "[]", legacy_vector, _dt(2024, 1, 1).isoformat()),
    )
    connection.commit()

    index = PostgresRetrievalIndex("postgresql://unit/solomon", connect=lambda _dsn: connection)
    indexed = index.upsert_item(_item("new", "structure x regulation r"))

    columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(retrieval_index)").fetchall()}
    legacy = connection.execute("SELECT embedding FROM retrieval_index WHERE item_id = ?", ("legacy",)).fetchone()
    current = connection.execute("SELECT embedding FROM retrieval_index WHERE item_id = ?", ("new",)).fetchone()
    migrations = connection.execute(
        "SELECT version FROM schema_migrations WHERE scope = ? ORDER BY version",
        ("postgres-retrieval-index:public",),
    ).fetchall()
    hnsw_index = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?",
        ("idx_retrieval_embedding_hnsw",),
    ).fetchone()
    full_text_index = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?",
        ("idx_retrieval_content_tsv",),
    ).fetchone()

    assert columns >= {"content_tsv", "embedding", "vector_json"}
    assert legacy is not None and str(legacy["embedding"]) == legacy_vector
    assert current is not None and len(json.loads(str(current["embedding"]))) == 256
    assert indexed.embedding_ref == "hashed-token-vector:1"
    assert [int(row["version"]) for row in migrations] == [1, 2, 3, 4]
    assert hnsw_index is not None
    assert full_text_index is not None


def test_postgres_retrieval_applies_pgvector_migrations_per_schema(tmp_path: Path) -> None:
    connection = _connect(tmp_path)
    default = PostgresRetrievalIndex("postgresql://unit/solomon", connect=lambda _dsn: connection)
    tenant = PostgresRetrievalIndex("postgresql://unit/solomon", connect=lambda _dsn: connection, schema="tenant-a")

    default.upsert_item(_item("default", "default structure"))
    tenant.upsert_item(_item("tenant", "tenant structure"))

    scopes = connection.execute(
        "SELECT scope, version FROM schema_migrations WHERE scope LIKE ? ORDER BY scope, version",
        ("postgres-retrieval-index:%",),
    ).fetchall()
    tenant_embedding = connection.execute(
        'SELECT embedding FROM "tenant_a__retrieval_index" WHERE item_id = ?',
        ("tenant",),
    ).fetchone()

    assert [(str(row["scope"]), int(row["version"])) for row in scopes] == [
        ("postgres-retrieval-index:public", 1),
        ("postgres-retrieval-index:public", 2),
        ("postgres-retrieval-index:public", 3),
        ("postgres-retrieval-index:public", 4),
        ("postgres-retrieval-index:tenant_a", 1),
        ("postgres-retrieval-index:tenant_a", 2),
        ("postgres-retrieval-index:tenant_a", 3),
        ("postgres-retrieval-index:tenant_a", 4),
    ]
    assert tenant_embedding is not None


def test_postgres_retrieval_rolls_back_a_failed_pgvector_migration(tmp_path: Path) -> None:
    class FailingHnswConnection(FakePostgresConnection):
        def execute(self, sql: str, params: tuple[object, ...] = ()) -> object:
            if "USING hnsw" in sql:
                raise RuntimeError("hnsw unavailable")
            return super().execute(sql, params)

    connection = FailingHnswConnection(tmp_path / "postgres.sqlite3")
    connection.begin()

    with pytest.raises(RuntimeError, match="hnsw unavailable"):
        PostgresRetrievalIndex("postgresql://unit/solomon", connect=lambda _dsn: connection)

    table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("retrieval_index",),
    ).fetchone()

    assert table is None


def test_postgres_retrieval_fails_when_pgvector_cannot_be_confirmed(tmp_path: Path) -> None:
    class MissingPgvectorConnection(FakePostgresConnection):
        def execute(self, sql: str, params: tuple[object, ...] = ()) -> object:
            if "FROM pg_extension WHERE extname" in sql:
                return self._conn.execute("SELECT 1 WHERE 0")
            return super().execute(sql, params)

    connection = MissingPgvectorConnection(tmp_path / "postgres.sqlite3")

    with pytest.raises(PostgresVectorExtensionError, match="pgvector"):
        PostgresRetrievalIndex("postgresql://unit/solomon", connect=lambda _dsn: connection)
