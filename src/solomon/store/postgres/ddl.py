# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from solomon.store.migrations import SchemaMigration
from solomon.store.postgres.connection import PostgresVectorExtensionError, quote_identifier


class ExecuteSQL(Protocol):
    def __call__(self, sql: str, params: tuple[Any, ...] = ()) -> Any: ...


NameResolver = Callable[[str], str]
POSTGRES_VECTOR_DIMENSIONS = 256


def create_schema_if_needed(execute: ExecuteSQL, schema: str | None) -> None:
    if schema is not None:
        execute(f"CREATE SCHEMA IF NOT EXISTS {quote_identifier(schema)}")


def create_knowledge_store_schema(execute: ExecuteSQL, table: NameResolver, index: NameResolver) -> None:
    execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table("knowledge_events")} (
            seq BIGSERIAL PRIMARY KEY,
            event_id TEXT NOT NULL UNIQUE,
            event_type TEXT NOT NULL,
            item_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table("knowledge_items")} (
            item_id TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            item_json TEXT NOT NULL,
            currency_state TEXT NOT NULL,
            valid_from TEXT NOT NULL,
            valid_to TEXT,
            ingested_at TEXT NOT NULL,
            successor_id TEXT,
            matter_id TEXT,
            client_id TEXT
        )
        """
    )
    execute(
        f"CREATE INDEX IF NOT EXISTS {index('idx_knowledge_items_state')} "
        f"ON {table('knowledge_items')}(currency_state)"
    )
    execute(
        f"CREATE INDEX IF NOT EXISTS {index('idx_knowledge_items_scope')} "
        f"ON {table('knowledge_items')}(matter_id, client_id)"
    )
    execute(
        f"CREATE INDEX IF NOT EXISTS {index('idx_knowledge_events_time')} "
        f"ON {table('knowledge_events')}(occurred_at, seq)"
    )


def create_graph_store_schema(execute: ExecuteSQL, table: NameResolver, index: NameResolver) -> None:
    execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table("dependency_edge_events")} (
            seq BIGSERIAL PRIMARY KEY,
            event_id TEXT NOT NULL UNIQUE,
            event_type TEXT NOT NULL,
            edge_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table("dependency_edges")} (
            edge_id TEXT PRIMARY KEY,
            edge_json TEXT NOT NULL,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            edge_type TEXT NOT NULL,
            target_kind TEXT NOT NULL,
            valid_from TEXT NOT NULL,
            valid_to TEXT,
            confidence TEXT NOT NULL
        )
        """
    )
    execute(f"CREATE INDEX IF NOT EXISTS {index('idx_edges_source')} ON {table('dependency_edges')}(source_id)")
    execute(f"CREATE INDEX IF NOT EXISTS {index('idx_edges_target')} ON {table('dependency_edges')}(target_id)")
    execute(
        f"CREATE INDEX IF NOT EXISTS {index('idx_edges_current_target')} "
        f"ON {table('dependency_edges')}(target_id, valid_to)"
    )
    execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table("dependency_suggestion_events")} (
            seq BIGSERIAL PRIMARY KEY,
            event_id TEXT NOT NULL UNIQUE,
            event_type TEXT NOT NULL,
            suggestion_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table("dependency_suggestions")} (
            suggestion_id TEXT PRIMARY KEY,
            suggestion_json TEXT NOT NULL,
            item_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            edge_type TEXT NOT NULL,
            decision TEXT NOT NULL,
            created_at TEXT NOT NULL,
            decided_at TEXT,
            UNIQUE(item_id, target_id, edge_type)
        )
        """
    )
    execute(
        f"CREATE INDEX IF NOT EXISTS {index('idx_suggestions_item')} "
        f"ON {table('dependency_suggestions')}(item_id)"
    )
    execute(
        f"CREATE INDEX IF NOT EXISTS {index('idx_suggestions_decision')} "
        f"ON {table('dependency_suggestions')}(decision)"
    )


def ensure_pgvector_extension(execute: ExecuteSQL) -> None:
    try:
        execute("CREATE EXTENSION IF NOT EXISTS vector")
    except Exception as exc:
        raise PostgresVectorExtensionError(
            "Postgres retrieval requires the self-hosted pgvector extension and CREATE EXTENSION privilege"
        ) from exc
    if execute("SELECT 1 FROM pg_extension WHERE extname = %s", ("vector",)).fetchone() is None:
        raise PostgresVectorExtensionError("Postgres retrieval requires the self-hosted pgvector extension")


def retrieval_index_migrations(
    table: NameResolver,
    index: NameResolver,
    *,
    scope: str,
) -> tuple[SchemaMigration, ...]:
    return (
        SchemaMigration(
            scope=scope,
            version=1,
            name="retrieval-index-base-schema",
            sqlite_statements=(),
            postgres_statements=(
                f"""
                CREATE TABLE IF NOT EXISTS {table("retrieval_index")} (
                    item_id TEXT PRIMARY KEY,
                    embedding_ref TEXT NOT NULL,
                    tokens_json TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    indexed_at TEXT NOT NULL
                )
                """,
                f"CREATE INDEX IF NOT EXISTS {index('idx_retrieval_ref')} ON {table('retrieval_index')}(embedding_ref)",
            ),
        ),
        SchemaMigration(
            scope=scope,
            version=2,
            name="pgvector-embedding-and-hnsw-index",
            sqlite_statements=(),
            postgres_statements=(
                f"""
                ALTER TABLE {table("retrieval_index")}
                ADD COLUMN IF NOT EXISTS embedding vector({POSTGRES_VECTOR_DIMENSIONS})
                """,
                f"""
                UPDATE {table("retrieval_index")}
                SET embedding = vector_json::vector({POSTGRES_VECTOR_DIMENSIONS})
                WHERE embedding IS NULL
                """,
                f"ALTER TABLE {table('retrieval_index')} ALTER COLUMN embedding SET NOT NULL",
                f"""
                CREATE INDEX IF NOT EXISTS {index('idx_retrieval_embedding_hnsw')}
                ON {table("retrieval_index")} USING hnsw (embedding vector_cosine_ops)
                """,
            ),
        ),
    )
