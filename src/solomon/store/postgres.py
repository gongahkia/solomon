# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib
import json
import re
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from typing_extensions import Self

from solomon.currency.models import CurrencyState, KnowledgeItem, now_utc
from solomon.graph.models import DependencyEdge
from solomon.orchestrator.retrieval import (
    EmbeddingStrategy,
    IndexedHit,
    _cosine_similarity,
    _embed_tokens,
    semantic_tokens,
)
from solomon.store.sqlite import ItemNotFoundError, StoreError

ConnectCallable = Callable[[str], Any]
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PostgresDependencyError(StoreError):
    """Raised when the optional Postgres driver is unavailable."""


class PostgresKnowledgeStore:
    """Append-only Postgres event store with a materialised current-state table."""

    def __init__(
        self,
        dsn: str,
        *,
        connect: ConnectCallable | None = None,
        schema: str | None = None,
    ) -> None:
        self.dsn = dsn
        self.schema = _normalize_schema(schema)
        self._conn = (connect or _default_connect)(dsn)
        self.initialize()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def initialize(self) -> None:
        with self._transaction():
            self._create_schema_if_needed()
            self._execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table("knowledge_events")} (
                    seq BIGSERIAL PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            self._execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table("knowledge_items")} (
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
            self._execute(
                f"CREATE INDEX IF NOT EXISTS {self._index('idx_knowledge_items_state')} "
                f"ON {self._table('knowledge_items')}(currency_state)"
            )
            self._execute(
                f"CREATE INDEX IF NOT EXISTS {self._index('idx_knowledge_items_scope')} "
                f"ON {self._table('knowledge_items')}(matter_id, client_id)"
            )
            self._execute(
                f"CREATE INDEX IF NOT EXISTS {self._index('idx_knowledge_events_time')} "
                f"ON {self._table('knowledge_events')}(occurred_at, seq)"
            )

    def write_item(self, item: KnowledgeItem) -> KnowledgeItem:
        with self._transaction():
            self._append_event(
                event_type="knowledge_item_written",
                item_id=item.id,
                occurred_at=item.ingested_at,
                payload={"item": item.model_dump(mode="json")},
            )
            self._upsert_current(item)
        return item

    def update_item(
        self,
        item: KnowledgeItem,
        *,
        event_type: str = "knowledge_item_updated",
        occurred_at: datetime | None = None,
    ) -> KnowledgeItem:
        with self._transaction():
            self._append_event(
                event_type=event_type,
                item_id=item.id,
                occurred_at=occurred_at or now_utc(),
                payload={"item": item.model_dump(mode="json")},
            )
            self._upsert_current(item)
        return item

    def get_item(self, item_id: str) -> KnowledgeItem:
        row = self._execute(
            f"SELECT item_json FROM {self._table('knowledge_items')} WHERE item_id = %s",
            (item_id,),
        ).fetchone()
        if row is None:
            raise ItemNotFoundError(item_id)
        return _item_from_json(_row_value(row, "item_json"))

    def get_many(
        self,
        item_ids: Iterable[str] | None = None,
        *,
        include_states: set[CurrencyState] | None = None,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> list[KnowledgeItem]:
        clauses: list[str] = []
        params: list[Any] = []
        if item_ids is not None:
            ids = list(item_ids)
            if not ids:
                return []
            placeholders = ",".join("%s" for _ in ids)
            clauses.append(f"item_id IN ({placeholders})")
            params.extend(ids)
        if include_states is not None:
            states = [state.value for state in include_states]
            if not states:
                return []
            placeholders = ",".join("%s" for _ in states)
            clauses.append(f"currency_state IN ({placeholders})")
            params.extend(states)
        if matter_id is not None:
            clauses.append("matter_id = %s")
            params.append(matter_id)
        if client_id is not None:
            clauses.append("client_id = %s")
            params.append(client_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._execute(
            f"SELECT item_json FROM {self._table('knowledge_items')} {where} ORDER BY ingested_at, item_id",
            tuple(params),
        ).fetchall()
        return [_item_from_json(_row_value(row, "item_json")) for row in rows]

    def supersede(
        self,
        predecessor_id: str,
        successor: KnowledgeItem,
        *,
        superseded_at: datetime | None = None,
    ) -> tuple[KnowledgeItem, KnowledgeItem]:
        effective_time = superseded_at or successor.valid_from or now_utc()
        predecessor = self.get_item(predecessor_id)
        closed_predecessor = predecessor.superseded_copy(successor_id=successor.id, valid_to=effective_time)
        successor_metadata = dict(successor.metadata)
        successor_metadata.setdefault("supersedes", predecessor_id)
        successor = successor.model_copy(update={"metadata": successor_metadata})

        with self._transaction():
            self._append_event(
                event_type="knowledge_item_superseded",
                item_id=predecessor_id,
                occurred_at=effective_time,
                payload={
                    "predecessor": closed_predecessor.model_dump(mode="json"),
                    "successor": successor.model_dump(mode="json"),
                },
            )
            self._upsert_current(closed_predecessor)
            self._upsert_current(successor)
        return closed_predecessor, successor

    def as_of(self, timestamp: datetime) -> list[KnowledgeItem]:
        rows = self._execute(
            f"""
            SELECT event_type, payload_json
            FROM {self._table("knowledge_events")}
            WHERE occurred_at <= %s
            ORDER BY occurred_at, seq
            """,
            (timestamp.isoformat(),),
        ).fetchall()
        return _events_to_state(rows)

    def snapshot(self, destination: Path | str) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        rows = self._execute(
            f"""
            SELECT event_id, event_type, item_id, occurred_at, payload_json
            FROM {self._table("knowledge_events")}
            ORDER BY seq
            """
        ).fetchall()
        events = [
            {
                "event_id": _row_value(row, "event_id"),
                "event_type": _row_value(row, "event_type"),
                "item_id": _row_value(row, "item_id"),
                "occurred_at": _row_value(row, "occurred_at"),
                "payload_json": _payload_json_text(_row_value(row, "payload_json")),
            }
            for row in rows
        ]
        target.write_text(json.dumps({"schema": "solomon.snapshot.v1", "events": events}, indent=2, sort_keys=True))
        return target

    @classmethod
    def restore(
        cls,
        snapshot: Path | str,
        dsn: str,
        *,
        connect: ConnectCallable | None = None,
        schema: str | None = None,
    ) -> PostgresKnowledgeStore:
        target = cls(dsn, connect=connect, schema=schema)
        raw = json.loads(Path(snapshot).read_text(encoding="utf-8"))
        if raw.get("schema") != "solomon.snapshot.v1":
            raise StoreError("unsupported snapshot schema")
        with target._transaction():
            for event in raw.get("events", []):
                target._execute(
                    f"""
                    INSERT INTO {target._table("knowledge_events")}
                    (event_id, event_type, item_id, occurred_at, payload_json)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT(event_id) DO NOTHING
                    """,
                    (
                        event["event_id"],
                        event["event_type"],
                        event["item_id"],
                        event["occurred_at"],
                        event["payload_json"],
                    ),
                )
            target.rebuild_current_state(commit=False)
        return target

    def rebuild_current_state(self, *, commit: bool = True) -> None:
        rows = self._execute(
            f"""
            SELECT event_type, payload_json
            FROM {self._table("knowledge_events")}
            ORDER BY occurred_at, seq
            """
        ).fetchall()
        state = _events_to_state(rows)

        def rebuild() -> None:
            self._execute(f"TRUNCATE TABLE {self._table('knowledge_items')}")
            for item in state:
                self._upsert_current(item)

        if commit:
            with self._transaction():
                rebuild()
        else:
            rebuild()

    def _append_event(
        self,
        *,
        event_type: str,
        item_id: str,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> None:
        event_id = f"{item_id}:{event_type}:{occurred_at.isoformat()}:{len(json.dumps(payload, sort_keys=True))}"
        self._execute(
            f"""
            INSERT INTO {self._table("knowledge_events")}
            (event_id, event_type, item_id, occurred_at, payload_json)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                event_id,
                event_type,
                item_id,
                occurred_at.isoformat(),
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
            ),
        )

    def _upsert_current(self, item: KnowledgeItem) -> None:
        self._execute(
            f"""
            INSERT INTO {self._table("knowledge_items")}
            (item_id, schema_version, item_json, currency_state, valid_from, valid_to, ingested_at,
             successor_id, matter_id, client_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(item_id) DO UPDATE SET
                schema_version = EXCLUDED.schema_version,
                item_json = EXCLUDED.item_json,
                currency_state = EXCLUDED.currency_state,
                valid_from = EXCLUDED.valid_from,
                valid_to = EXCLUDED.valid_to,
                ingested_at = EXCLUDED.ingested_at,
                successor_id = EXCLUDED.successor_id,
                matter_id = EXCLUDED.matter_id,
                client_id = EXCLUDED.client_id
            """,
            (
                item.id,
                item.schema_version,
                item.model_dump_json(),
                item.currency_state.value,
                item.valid_from.isoformat(),
                item.valid_to.isoformat() if item.valid_to else None,
                item.ingested_at.isoformat(),
                item.successor_id,
                item.matter_id,
                item.client_id,
            ),
        )

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

    def _create_schema_if_needed(self) -> None:
        if self.schema is not None:
            self._execute(f"CREATE SCHEMA IF NOT EXISTS {_quote_identifier(self.schema)}")

    def _table(self, name: str) -> str:
        return _qualified(self.schema, name)

    def _index(self, name: str) -> str:
        if self.schema is None:
            return _quote_identifier(name)
        return _quote_identifier(f"{self.schema}_{name}")


class PostgresGraphStore:
    """Bi-temporal dependency graph tables backed by Postgres."""

    def __init__(
        self,
        dsn: str,
        *,
        connect: ConnectCallable | None = None,
        schema: str | None = None,
    ) -> None:
        self.dsn = dsn
        self.schema = _normalize_schema(schema)
        self._conn = (connect or _default_connect)(dsn)
        self.initialize()

    def close(self) -> None:
        self._conn.close()

    def initialize(self) -> None:
        with self._transaction():
            if self.schema is not None:
                self._execute(f"CREATE SCHEMA IF NOT EXISTS {_quote_identifier(self.schema)}")
            self._execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table("dependency_edge_events")} (
                    seq BIGSERIAL PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    edge_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            self._execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table("dependency_edges")} (
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
            self._execute(
                f"CREATE INDEX IF NOT EXISTS {self._index('idx_edges_source')} "
                f"ON {self._table('dependency_edges')}(source_id)"
            )
            self._execute(
                f"CREATE INDEX IF NOT EXISTS {self._index('idx_edges_target')} "
                f"ON {self._table('dependency_edges')}(target_id)"
            )
            self._execute(
                f"CREATE INDEX IF NOT EXISTS {self._index('idx_edges_current_target')} "
                f"ON {self._table('dependency_edges')}(target_id, valid_to)"
            )

    def add_dependency(self, edge: DependencyEdge) -> DependencyEdge:
        with self._transaction():
            self._append_event(
                event_type="dependency_edge_added",
                edge_id=edge.id,
                occurred_at=edge.created_at,
                payload={"edge": edge.model_dump(mode="json")},
            )
            self._upsert_edge(edge)
        return edge

    def close_dependency(self, edge_id: str, *, valid_to: datetime) -> DependencyEdge:
        edge = self.get_edge(edge_id)
        closed = edge.model_copy(update={"valid_to": valid_to})
        with self._transaction():
            self._append_event(
                event_type="dependency_edge_closed",
                edge_id=edge_id,
                occurred_at=valid_to,
                payload={"edge": closed.model_dump(mode="json")},
            )
            self._upsert_edge(closed)
        return closed

    def get_edge(self, edge_id: str) -> DependencyEdge:
        row = self._execute(
            f"SELECT edge_json FROM {self._table('dependency_edges')} WHERE edge_id = %s",
            (edge_id,),
        ).fetchone()
        if row is None:
            raise KeyError(edge_id)
        return _edge_from_json(_row_value(row, "edge_json"))

    def get_dependencies(self, item_id: str, *, at: datetime | None = None) -> list[DependencyEdge]:
        return self._select_edges("source_id = %s", [item_id], at=at)

    def get_dependents(self, authority_or_item_id: str, *, at: datetime | None = None) -> list[DependencyEdge]:
        return self._select_edges("target_id = %s", [authority_or_item_id], at=at)

    def impact_edges(self, authority_or_item_id: str) -> list[DependencyEdge]:
        return self.get_dependents(authority_or_item_id)

    def centrality(self, item_or_authority_ids: Iterable[str] | None = None) -> dict[str, int]:
        ids = list(item_or_authority_ids or [])
        if ids:
            placeholders = ",".join("%s" for _ in ids)
            rows = self._execute(
                f"""
                SELECT target_id, COUNT(*) AS count
                FROM {self._table("dependency_edges")}
                WHERE valid_to IS NULL AND target_id IN ({placeholders})
                GROUP BY target_id
                """,
                tuple(ids),
            ).fetchall()
        else:
            rows = self._execute(
                f"""
                SELECT target_id, COUNT(*) AS count
                FROM {self._table("dependency_edges")}
                WHERE valid_to IS NULL
                GROUP BY target_id
                """
            ).fetchall()
        return {str(_row_value(row, "target_id")): int(_row_value(row, "count")) for row in rows}

    def subgraph_for_items(self, item_ids: Iterable[str]) -> list[DependencyEdge]:
        ids = list(item_ids)
        if not ids:
            return []
        placeholders = ",".join("%s" for _ in ids)
        rows = self._execute(
            f"""
            SELECT edge_json
            FROM {self._table("dependency_edges")}
            WHERE valid_to IS NULL
              AND (source_id IN ({placeholders}) OR target_id IN ({placeholders}))
            ORDER BY source_id, target_id, edge_id
            """,
            tuple([*ids, *ids]),
        ).fetchall()
        return [_edge_from_json(_row_value(row, "edge_json")) for row in rows]

    def subgraph_for_scope(
        self,
        *,
        store: Any,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> list[DependencyEdge]:
        scoped_items = store.get_many(matter_id=matter_id, client_id=client_id)
        return self.subgraph_for_items(item.id for item in scoped_items)

    def _select_edges(self, clause: str, params: list[Any], *, at: datetime | None) -> list[DependencyEdge]:
        time_clause = "valid_to IS NULL" if at is None else "valid_from <= %s AND (valid_to IS NULL OR valid_to > %s)"
        time_params = [] if at is None else [at.isoformat(), at.isoformat()]
        rows = self._execute(
            f"""
            SELECT edge_json
            FROM {self._table("dependency_edges")}
            WHERE {clause} AND {time_clause}
            ORDER BY valid_from, edge_id
            """,
            tuple([*params, *time_params]),
        ).fetchall()
        return [_edge_from_json(_row_value(row, "edge_json")) for row in rows]

    def _append_event(
        self,
        *,
        event_type: str,
        edge_id: str,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> None:
        event_id = f"{edge_id}:{event_type}:{occurred_at.isoformat()}:{len(json.dumps(payload, sort_keys=True))}"
        self._execute(
            f"""
            INSERT INTO {self._table("dependency_edge_events")}
            (event_id, event_type, edge_id, occurred_at, payload_json)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                event_id,
                event_type,
                edge_id,
                occurred_at.isoformat(),
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
            ),
        )

    def _upsert_edge(self, edge: DependencyEdge) -> None:
        self._execute(
            f"""
            INSERT INTO {self._table("dependency_edges")}
            (edge_id, edge_json, source_id, target_id, edge_type, target_kind,
             valid_from, valid_to, confidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(edge_id) DO UPDATE SET
                edge_json = EXCLUDED.edge_json,
                source_id = EXCLUDED.source_id,
                target_id = EXCLUDED.target_id,
                edge_type = EXCLUDED.edge_type,
                target_kind = EXCLUDED.target_kind,
                valid_from = EXCLUDED.valid_from,
                valid_to = EXCLUDED.valid_to,
                confidence = EXCLUDED.confidence
            """,
            (
                edge.id,
                edge.model_dump_json(),
                edge.source_id,
                edge.target_id,
                edge.edge_type.value,
                edge.target_kind,
                edge.valid_from.isoformat(),
                edge.valid_to.isoformat() if edge.valid_to else None,
                edge.confidence.value,
            ),
        )

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
        return _qualified(self.schema, name)

    def _index(self, name: str) -> str:
        if self.schema is None:
            return _quote_identifier(name)
        return _quote_identifier(f"{self.schema}_{name}")


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
        self.schema = _normalize_schema(schema)
        self.strategy = strategy or EmbeddingStrategy()
        self._conn = (connect or _default_connect)(dsn)
        self.initialize()

    def initialize(self) -> None:
        with self._transaction():
            if self.schema is not None:
                self._execute(f"CREATE SCHEMA IF NOT EXISTS {_quote_identifier(self.schema)}")
            self._execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table("retrieval_index")} (
                    item_id TEXT PRIMARY KEY,
                    embedding_ref TEXT NOT NULL,
                    tokens_json TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    indexed_at TEXT NOT NULL
                )
                """
            )
            self._execute(
                f"CREATE INDEX IF NOT EXISTS {self._index('idx_retrieval_ref')} "
                f"ON {self._table('retrieval_index')}(embedding_ref)"
            )

    def upsert_item(self, item: KnowledgeItem, *, indexed_at: datetime | None = None) -> KnowledgeItem:
        embedding_ref = self.strategy.ref
        tokens = sorted(semantic_tokens(item.content))
        vector = _embed_tokens(tokens, dimensions=self.strategy.dimensions)
        timestamp = indexed_at or now_utc()
        with self._transaction():
            self._execute(
                f"""
                INSERT INTO {self._table("retrieval_index")}
                (item_id, embedding_ref, tokens_json, vector_json, indexed_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT(item_id) DO UPDATE SET
                    embedding_ref = EXCLUDED.embedding_ref,
                    tokens_json = EXCLUDED.tokens_json,
                    vector_json = EXCLUDED.vector_json,
                    indexed_at = EXCLUDED.indexed_at
                """,
                (item.id, embedding_ref, json.dumps(tokens), json.dumps(vector), timestamp.isoformat()),
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
        return {str(_row_value(row, "item_id")): str(_row_value(row, "embedding_ref")) for row in rows}

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
            score = _cosine_similarity(query_vector, json.loads(str(_row_value(row, "vector_json"))))
            if score > 0:
                hits.append(
                    IndexedHit(
                        item_id=str(_row_value(row, "item_id")),
                        similarity=score,
                        embedding_ref=str(_row_value(row, "embedding_ref")),
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
        return _qualified(self.schema, name)

    def _index(self, name: str) -> str:
        if self.schema is None:
            return _quote_identifier(name)
        return _quote_identifier(f"{self.schema}_{name}")


def _default_connect(dsn: str) -> Any:
    try:
        psycopg = importlib.import_module("psycopg")
        rows = importlib.import_module("psycopg.rows")
    except ModuleNotFoundError as exc:
        raise PostgresDependencyError(
            "Postgres backend requires the optional server dependency: install solomon[server]"
        ) from exc
    return psycopg.connect(dsn, row_factory=rows.dict_row, autocommit=False)


def _events_to_state(rows: Iterable[Any]) -> list[KnowledgeItem]:
    state: dict[str, KnowledgeItem] = {}
    for row in rows:
        payload = json.loads(_payload_json_text(_row_value(row, "payload_json")))
        event_type = str(_row_value(row, "event_type"))
        if event_type in {
            "knowledge_item_written",
            "knowledge_item_updated",
            "knowledge_item_stale_flagged",
            "knowledge_item_indexed",
        }:
            item = KnowledgeItem.model_validate(payload["item"])
            state[item.id] = item
        elif event_type == "knowledge_item_superseded":
            predecessor = KnowledgeItem.model_validate(payload["predecessor"])
            successor = KnowledgeItem.model_validate(payload["successor"])
            state[predecessor.id] = predecessor
            state[successor.id] = successor
    return sorted(state.values(), key=lambda item: (item.ingested_at, item.id))


def _item_from_json(value: Any) -> KnowledgeItem:
    if isinstance(value, str):
        return KnowledgeItem.model_validate_json(value)
    return KnowledgeItem.model_validate(value)


def _edge_from_json(value: Any) -> DependencyEdge:
    if isinstance(value, str):
        return DependencyEdge.model_validate_json(value)
    return DependencyEdge.model_validate(value)


def _payload_json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _row_value(row: Any, key: str) -> Any:
    return row[key]


def _normalize_schema(schema: str | None) -> str | None:
    if schema is None:
        return None
    normalized = re.sub(r"[^A-Za-z0-9_]", "_", schema)
    if not normalized or normalized[0].isdigit():
        normalized = f"tenant_{normalized}"
    if not IDENTIFIER_RE.fullmatch(normalized):
        raise StoreError(f"invalid Postgres schema identifier: {schema}")
    return normalized


def _quote_identifier(value: str) -> str:
    if not IDENTIFIER_RE.fullmatch(value):
        raise StoreError(f"invalid SQL identifier: {value}")
    return f'"{value}"'


def _qualified(schema: str | None, table: str) -> str:
    quoted_table = _quote_identifier(table)
    if schema is None:
        return quoted_table
    return f"{_quote_identifier(schema)}.{quoted_table}"
