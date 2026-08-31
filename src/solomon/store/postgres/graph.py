# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from threading import RLock
from typing import Any

from solomon.graph.models import DependencyEdge
from solomon.graph.suggestions import DependencySuggestion, SuggestionDecision
from solomon.store.postgres.connection import (
    ConnectCallable,
    default_connect,
    normalize_schema,
    qualified,
    quote_identifier,
)
from solomon.store.postgres.ddl import create_graph_store_schema, create_schema_if_needed
from solomon.store.postgres.serialization import edge_from_json, row_value, suggestion_from_json


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
        self.schema = normalize_schema(schema)
        self._lock = RLock()
        self._conn = (connect or default_connect)(dsn)
        self.initialize()

    def close(self) -> None:
        self._conn.close()

    def initialize(self) -> None:
        with self._transaction():
            create_schema_if_needed(self._execute, self.schema)
            create_graph_store_schema(self._execute, self._table, self._index)

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

    def add_dependency_suggestion(self, suggestion: DependencySuggestion) -> DependencySuggestion:
        with self._transaction():
            self._append_suggestion_event(
                event_type="dependency_suggestion_created",
                suggestion=suggestion,
                occurred_at=suggestion.created_at,
            )
            self._upsert_suggestion(suggestion)
        return suggestion

    def update_dependency_suggestion(self, suggestion: DependencySuggestion) -> DependencySuggestion:
        with self._transaction():
            self._append_suggestion_event(
                event_type=f"dependency_suggestion_{suggestion.decision.value}",
                suggestion=suggestion,
                occurred_at=suggestion.decided_at or suggestion.created_at,
            )
            self._upsert_suggestion(suggestion)
        return suggestion

    def get_dependency_suggestion(self, suggestion_id: str) -> DependencySuggestion:
        row = self._execute(
            f"""
            SELECT suggestion_json
            FROM {self._table("dependency_suggestions")}
            WHERE suggestion_id = %s
            """,
            (suggestion_id,),
        ).fetchone()
        if row is None:
            raise KeyError(suggestion_id)
        return suggestion_from_json(row_value(row, "suggestion_json"))

    def list_dependency_suggestions(
        self,
        *,
        item_id: str | None = None,
        decision: SuggestionDecision | None = None,
        source: str | None = None,
        target_id: str | None = None,
        created_by: str | None = None,
        needs_reverification: bool | None = None,
        limit: int = 100,
    ) -> list[DependencySuggestion]:
        clauses: list[str] = []
        params: list[Any] = []
        if item_id is not None:
            clauses.append("item_id = %s")
            params.append(item_id)
        if decision is not None:
            clauses.append("decision = %s")
            params.append(decision.value)
        if source is not None:
            clauses.append("source = %s")
            params.append(source)
        if target_id is not None:
            clauses.append("target_id = %s")
            params.append(target_id)
        if created_by is not None:
            clauses.append("created_by = %s")
            params.append(created_by)
        if needs_reverification is not None:
            clauses.append("needs_reverification = %s")
            params.append(needs_reverification)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._execute(
            f"""
            SELECT suggestion_json
            FROM {self._table("dependency_suggestions")}
            {where}
            ORDER BY created_at, suggestion_id
            LIMIT %s
            """,
            tuple([*params, limit]),
        ).fetchall()
        return [suggestion_from_json(row_value(row, "suggestion_json")) for row in rows]

    def list_dependency_suggestion_events(self, suggestion_id: str) -> list[dict[str, object]]:
        rows = self._execute(
            f"""
            SELECT event_id, event_type, occurred_at, payload_json
            FROM {self._table("dependency_suggestion_events")}
            WHERE suggestion_id = %s
            ORDER BY seq
            """,
            (suggestion_id,),
        ).fetchall()
        return [
            {
                "event_id": str(row_value(row, "event_id")),
                "event_type": str(row_value(row, "event_type")),
                "occurred_at": str(row_value(row, "occurred_at")),
                "payload": json.loads(str(row_value(row, "payload_json"))),
            }
            for row in rows
        ]

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
        return edge_from_json(row_value(row, "edge_json"))

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
        return {str(row_value(row, "target_id")): int(row_value(row, "count")) for row in rows}

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
        return [edge_from_json(row_value(row, "edge_json")) for row in rows]

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
        return [edge_from_json(row_value(row, "edge_json")) for row in rows]

    def _append_event(
        self,
        *,
        event_type: str,
        edge_id: str,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> None:
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        event_id = (
            f"{edge_id}:{event_type}:{occurred_at.isoformat()}:{hashlib.sha256(payload_json.encode()).hexdigest()}"
        )
        self._execute(
            f"""
            INSERT INTO {self._table("dependency_edge_events")}
            (event_id, event_type, edge_id, occurred_at, payload_json)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING
            """,
            (
                event_id,
                event_type,
                edge_id,
                occurred_at.isoformat(),
                payload_json,
            ),
        )

    def _append_suggestion_event(
        self,
        *,
        event_type: str,
        suggestion: DependencySuggestion,
        occurred_at: datetime,
    ) -> None:
        payload = {"suggestion": suggestion.model_dump(mode="json")}
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        event_id = (
            f"{suggestion.id}:{event_type}:{occurred_at.isoformat()}:"
            f"{hashlib.sha256(payload_json.encode()).hexdigest()}"
        )
        self._execute(
            f"""
            INSERT INTO {self._table("dependency_suggestion_events")}
            (event_id, event_type, suggestion_id, occurred_at, payload_json)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING
            """,
            (
                event_id,
                event_type,
                suggestion.id,
                occurred_at.isoformat(),
                payload_json,
            ),
        )

    def _upsert_edge(self, edge: DependencyEdge) -> None:
        self._execute(
            f"""
            INSERT INTO {self._table("dependency_edges")}
            (edge_id, edge_json, source_id, target_id, edge_type, target_kind,
             valid_from, valid_to, confidence, source_suggestion_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(edge_id) DO UPDATE SET
                edge_json = EXCLUDED.edge_json,
                source_id = EXCLUDED.source_id,
                target_id = EXCLUDED.target_id,
                edge_type = EXCLUDED.edge_type,
                target_kind = EXCLUDED.target_kind,
                valid_from = EXCLUDED.valid_from,
                valid_to = EXCLUDED.valid_to,
                confidence = EXCLUDED.confidence,
                source_suggestion_id = EXCLUDED.source_suggestion_id
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
                edge.source_suggestion_id,
            ),
        )

    def _upsert_suggestion(self, suggestion: DependencySuggestion) -> None:
        self._execute(
            f"""
            INSERT INTO {self._table("dependency_suggestions")}
            (suggestion_id, suggestion_json, item_id, target_id, edge_type, decision, created_at, decided_at,
             source, assertion_type, created_by, idempotency_key, request_sha256, source_document_id,
             source_document_version, needs_reverification, state_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(suggestion_id) DO UPDATE SET
                suggestion_json = EXCLUDED.suggestion_json,
                decision = EXCLUDED.decision,
                decided_at = EXCLUDED.decided_at,
                needs_reverification = EXCLUDED.needs_reverification,
                state_version = EXCLUDED.state_version
            """,
            (
                suggestion.id,
                suggestion.model_dump_json(),
                suggestion.item_id,
                suggestion.suggested_edge.target_id,
                suggestion.suggested_edge.edge_type.value,
                suggestion.decision.value,
                suggestion.created_at.isoformat(),
                suggestion.decided_at.isoformat() if suggestion.decided_at else None,
                suggestion.source,
                suggestion.assertion_type.value if suggestion.assertion_type is not None else None,
                suggestion.created_by,
                suggestion.idempotency_key,
                suggestion.request_sha256,
                suggestion.source_document_id,
                suggestion.source_document_version,
                suggestion.needs_reverification,
                suggestion.state_version,
            ),
        )

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        return self._conn.execute(sql, params)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
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
