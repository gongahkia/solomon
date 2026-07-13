# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from solomon.contracts import EmbeddingRequest
from solomon.currency.models import KnowledgeItem, now_utc
from solomon.orchestrator.retrieval import (
    EmbeddingStrategy,
    HashedEmbeddingProvider,
    IndexedHit,
    LexicalHit,
    RetrievalEmbeddingProvider,
    semantic_tokens,
    tokenize,
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
        provider: RetrievalEmbeddingProvider | None = None,
    ) -> None:
        self.dsn = dsn
        self.schema = normalize_schema(schema)
        if strategy is not None and provider is not None:
            raise ValueError("set either an embedding strategy or provider")
        self.provider = provider or HashedEmbeddingProvider(strategy=strategy)
        self.strategy = self.provider.strategy
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
        lexical_tokens = sorted(tokenize(item.content))
        vector = self._embed_text(item.content)
        vector_literal = json.dumps(vector, separators=(",", ":"))
        timestamp = indexed_at or now_utc()
        with self._transaction():
            self._execute(
                f"""
                INSERT INTO {self._table("retrieval_index")}
                (
                    item_id, embedding_ref, tokens_json, lexical_tokens_json,
                    vector_json, content_tsv, embedding, indexed_at
                )
                VALUES (%s, %s, %s, %s, %s, to_tsvector('simple', %s), %s::vector, %s)
                ON CONFLICT(item_id) DO UPDATE SET
                    embedding_ref = EXCLUDED.embedding_ref,
                    tokens_json = EXCLUDED.tokens_json,
                    lexical_tokens_json = EXCLUDED.lexical_tokens_json,
                    vector_json = EXCLUDED.vector_json,
                    content_tsv = EXCLUDED.content_tsv,
                    embedding = EXCLUDED.embedding,
                    indexed_at = EXCLUDED.indexed_at
                """,
                (
                    item.id,
                    embedding_ref,
                    json.dumps(tokens),
                    json.dumps(lexical_tokens),
                    vector_literal,
                    item.content,
                    vector_literal,
                    timestamp.isoformat(),
                ),
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

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> list[IndexedHit]:
        if not tokenize(query):
            return []
        query_vector = self._embed_text(query)
        vector_literal = json.dumps(query_vector, separators=(",", ":"))
        scope_sql, scope_params = self._scope_clause(matter_id=matter_id, client_id=client_id)
        rows = self._execute(
            f"""
            SELECT retrieval.item_id, retrieval.embedding_ref,
                1 - (retrieval.embedding <=> %s::vector) AS similarity
            FROM {self._table("retrieval_index")} AS retrieval
            INNER JOIN {self._table("knowledge_items")} AS knowledge
                ON knowledge.item_id = retrieval.item_id
            WHERE retrieval.embedding_ref = %s {scope_sql}
            ORDER BY retrieval.embedding <=> %s::vector, retrieval.item_id
            LIMIT %s
            """,
            (vector_literal, self.strategy.ref, *scope_params, vector_literal, limit),
        ).fetchall()
        return [
            IndexedHit(
                item_id=str(row_value(row, "item_id")),
                similarity=float(row_value(row, "similarity")),
                embedding_ref=str(row_value(row, "embedding_ref")),
            )
            for row in rows
            if float(row_value(row, "similarity")) > 0
        ]

    def search_lexical(
        self,
        query: str,
        *,
        limit: int = 20,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> list[LexicalHit]:
        query_terms = tokenize(query)
        if not query_terms:
            return []
        scope_sql, scope_params = self._scope_clause(matter_id=matter_id, client_id=client_id)
        rows = self._execute(
            f"""
            SELECT retrieval.item_id,
                ts_rank_cd(retrieval.content_tsv, plainto_tsquery('simple', %s)) AS match_ratio
            FROM {self._table("retrieval_index")} AS retrieval
            INNER JOIN {self._table("knowledge_items")} AS knowledge
                ON knowledge.item_id = retrieval.item_id
            WHERE retrieval.content_tsv @@ plainto_tsquery('simple', %s) {scope_sql}
            ORDER BY match_ratio DESC, retrieval.item_id DESC
            LIMIT %s
            """,
            (query, query, *scope_params, limit),
        ).fetchall()
        return [
            LexicalHit(
                item_id=str(row_value(row, "item_id")),
                match_ratio=float(row_value(row, "match_ratio")),
                terms=sorted(query_terms),
            )
            for row in rows
        ]

    @staticmethod
    def _scope_clause(*, matter_id: str | None, client_id: str | None) -> tuple[str, tuple[str, ...]]:
        clauses: list[str] = []
        params: list[str] = []
        if matter_id is not None:
            clauses.append("knowledge.matter_id = %s")
            params.append(matter_id)
        if client_id is not None:
            clauses.append("knowledge.client_id = %s")
            params.append(client_id)
        return (f" AND {' AND '.join(clauses)}" if clauses else "", tuple(params))

    def _embed_text(self, text: str) -> list[float]:
        response = self.provider.embed(EmbeddingRequest(model=self.strategy.ref, texts=[text]))
        if len(response.vectors) != 1:
            raise ValueError("embedding provider returned an unexpected vector count")
        vector = response.vectors[0]
        if len(vector) != self.strategy.dimensions or not all(math.isfinite(value) for value in vector):
            raise ValueError("embedding provider returned an invalid vector")
        return vector

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
