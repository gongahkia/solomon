# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from solomon.store.postgres.connection import quote_identifier


class ExecuteSQL(Protocol):
    def __call__(self, sql: str, params: tuple[Any, ...] = ()) -> Any: ...


NameResolver = Callable[[str], str]


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


def create_retrieval_index_schema(execute: ExecuteSQL, table: NameResolver, index: NameResolver) -> None:
    execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table("retrieval_index")} (
            item_id TEXT PRIMARY KEY,
            embedding_ref TEXT NOT NULL,
            tokens_json TEXT NOT NULL,
            vector_json TEXT NOT NULL,
            indexed_at TEXT NOT NULL
        )
        """
    )
    execute(f"CREATE INDEX IF NOT EXISTS {index('idx_retrieval_ref')} ON {table('retrieval_index')}(embedding_ref)")
