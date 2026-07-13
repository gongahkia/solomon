# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from solomon.currency.models import KnowledgeItem, now_utc
from solomon.orchestrator.retrieval import (
    EmbeddingStrategy,
    IndexedHit,
    _cosine_similarity,
    _embed_tokens,
    semantic_tokens,
)
from solomon.store.migrations import apply_postgres_migrations
from solomon.store.postgres.connection import (
    ConnectCallable,
    default_connect,
    normalize_schema,
    qualified,
    quote_identifier,
)
from solomon.store.postgres.ddl import (
    POSTGRES_VECTOR_DIMENSIONS,
    create_schema_if_needed,
    ensure_pgvector_extension,
    retrieval_index_migrations,
)
from solomon.store.postgres.serialization import row_value


class PostgresRetrievalIndex:
    """Deterministic hashed-vector retrieval index backed by Postgres."""

    def __init__(
        self,
        dsn: str,
        *,
        connect: ConnectCallable | None = None,
        schema: str | None = None,
        strategy: EmbeddingStrategy | None = None,
    ) -> None:
        self.dsn = dsn
        self.schema = normalize_schema(schema)
        self.strategy = strategy or EmbeddingStrategy()
        if self.strategy.dimensions != POSTGRES_VECTOR_DIMENSIONS:
            raise ValueError(f"Postgres retrieval requires {POSTGRES_VECTOR_DIMENSIONS}-dimensional embeddings")
        self._conn = (connect or default_connect)(dsn)
        self.initialize()

    def initialize(self) -> None:
        with self._transaction():
            create_schema_if_needed(self._execute, self.schema)
            ensure_pgvector_extension(self._execute)
            apply_postgres_migrations(
                self._execute,
                retrieval_index_migrations(
                    self._table,
                    self._index,
                    scope=f"postgres-retrieval-index:{self.schema or 'public'}",
                ),
            )

    def upsert_item(self, item: KnowledgeItem, *, indexed_at: datetime | None = None) -> KnowledgeItem:
        embedding_ref = self.strategy.ref
        tokens = sorted(semantic_tokens(item.content))
        vector = _embed_tokens(tokens, dimensions=self.strategy.dimensions)
        vector_literal = json.dumps(vector, separators=(",", ":"))
        timestamp = indexed_at or now_utc()
        with self._transaction():
            self._execute(
                f"""
                INSERT INTO {self._table("retrieval_index")}
                (item_id, embedding_ref, tokens_json, vector_json, embedding, indexed_at)
                VALUES (%s, %s, %s, %s, %s::vector, %s)
                ON CONFLICT(item_id) DO UPDATE SET
                    embedding_ref = EXCLUDED.embedding_ref,
                    tokens_json = EXCLUDED.tokens_json,
                    vector_json = EXCLUDED.vector_json,
                    embedding = EXCLUDED.embedding,
                    indexed_at = EXCLUDED.indexed_at
                """,
                (item.id, embedding_ref, json.dumps(tokens), vector_literal, vector_literal, timestamp.isoformat()),
            )
        return item.model_copy(update={"embedding_ref": embedding_ref})

    def batch_upsert(self, items: list[KnowledgeItem]) -> list[KnowledgeItem]:
        return [self.upsert_item(item) for item in items]

    def embedding_refs(self, item_ids: list[str]) -> dict[str, str]:
        if not item_ids:
            return {}
        placeholders = ",".join("%s" for _ in item_ids)
        rows = self._execute(
            f"""
            SELECT item_id, embedding_ref
            FROM {self._table("retrieval_index")}
            WHERE item_id IN ({placeholders})
            """,
            tuple(item_ids),
        ).fetchall()
        return {str(row_value(row, "item_id")): str(row_value(row, "embedding_ref")) for row in rows}

    def search(self, query: str, *, limit: int = 20) -> list[IndexedHit]:
        query_tokens = semantic_tokens(query)
        if not query_tokens:
            return []
        query_vector = _embed_tokens(sorted(query_tokens), dimensions=self.strategy.dimensions)
        rows = self._execute(
            f"""
            SELECT item_id, embedding_ref, vector_json
            FROM {self._table("retrieval_index")}
            ORDER BY item_id
            """
        ).fetchall()
        hits: list[IndexedHit] = []
        for row in rows:
            score = _cosine_similarity(query_vector, json.loads(str(row_value(row, "vector_json"))))
            if score > 0:
                hits.append(
                    IndexedHit(
                        item_id=str(row_value(row, "item_id")),
                        similarity=score,
                        embedding_ref=str(row_value(row, "embedding_ref")),
                    )
                )
        return sorted(hits, key=lambda hit: (hit.similarity, hit.item_id), reverse=True)[:limit]

    def close(self) -> None:
        self._conn.close()

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        return self._conn.execute(sql, params)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
        except Exception:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()

    def _table(self, name: str) -> str:
        return qualified(self.schema, name)

    def _index(self, name: str) -> str:
        if self.schema is None:
            return quote_identifier(name)
        return quote_identifier(f"{self.schema}_{name}")
