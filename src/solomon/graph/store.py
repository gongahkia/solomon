# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

from solomon.graph.models import DependencyEdge, EdgeType
from solomon.graph.suggestions import DependencySuggestion, SuggestionDecision
from solomon.store.types import KnowledgeStoreProtocol


class GraphStore:
    """Bi-temporal dependency graph tables co-located with the knowledge SQLite database."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self.initialize()

    def close(self) -> None:
        self._conn.close()

    def initialize(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dependency_edge_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    edge_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dependency_edges (
                    edge_id TEXT PRIMARY KEY,
                    edge_json TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    target_kind TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_to TEXT,
                    confidence TEXT NOT NULL,
                    source_suggestion_id TEXT
                )
                """
            )
            edge_columns = {str(row["name"]) for row in self._conn.execute("PRAGMA table_info(dependency_edges)")}
            if "source_suggestion_id" not in edge_columns:
                self._conn.execute("ALTER TABLE dependency_edges ADD COLUMN source_suggestion_id TEXT")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON dependency_edges(source_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON dependency_edges(target_id)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_edges_current_target ON dependency_edges(target_id, valid_to)"
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dependency_suggestion_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    suggestion_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            self._migrate_dependency_suggestion_table_if_needed()
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dependency_suggestions (
                    suggestion_id TEXT PRIMARY KEY,
                    suggestion_json TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    source TEXT NOT NULL DEFAULT 'deterministic',
                    assertion_type TEXT,
                    created_by TEXT,
                    idempotency_key TEXT,
                    request_sha256 TEXT,
                    source_document_id TEXT,
                    source_document_version INTEGER,
                    needs_reverification INTEGER NOT NULL DEFAULT 0,
                    state_version INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_suggestions_item ON dependency_suggestions(item_id)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_suggestions_decision ON dependency_suggestions(decision)"
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_suggestions_target ON dependency_suggestions(target_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_suggestions_source ON dependency_suggestions(source)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_suggestions_reverification "
                "ON dependency_suggestions(needs_reverification, created_at)"
            )
            self._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_suggestions_idempotency "
                "ON dependency_suggestions(source, idempotency_key) WHERE idempotency_key IS NOT NULL"
            )
            self._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_assertion "
                "ON dependency_edges(source_suggestion_id) WHERE source_suggestion_id IS NOT NULL"
            )

    def _migrate_dependency_suggestion_table_if_needed(self) -> None:
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'dependency_suggestions'"
        ).fetchone()
        if row is None or "UNIQUE(item_id, target_id, edge_type)" not in str(row["sql"]):
            return
        self._conn.execute("DROP INDEX IF EXISTS idx_suggestions_item")
        self._conn.execute("DROP INDEX IF EXISTS idx_suggestions_decision")
        self._conn.execute("ALTER TABLE dependency_suggestions RENAME TO dependency_suggestions_legacy")
        self._conn.execute(
            """
            CREATE TABLE dependency_suggestions (
                suggestion_id TEXT PRIMARY KEY,
                suggestion_json TEXT NOT NULL,
                item_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                decision TEXT NOT NULL,
                created_at TEXT NOT NULL,
                decided_at TEXT,
                source TEXT NOT NULL DEFAULT 'deterministic',
                assertion_type TEXT,
                created_by TEXT,
                idempotency_key TEXT,
                request_sha256 TEXT,
                source_document_id TEXT,
                source_document_version INTEGER,
                needs_reverification INTEGER NOT NULL DEFAULT 0,
                state_version INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        self._conn.execute(
            """
            INSERT INTO dependency_suggestions
            (suggestion_id, suggestion_json, item_id, target_id, edge_type, decision, created_at, decided_at)
            SELECT suggestion_id, suggestion_json, item_id, target_id, edge_type, decision, created_at, decided_at
            FROM dependency_suggestions_legacy
            """
        )
        self._conn.execute("DROP TABLE dependency_suggestions_legacy")

    def add_dependency(self, edge: DependencyEdge) -> DependencyEdge:
        with self._lock, self._conn:
            self._append_event(
                event_type="dependency_edge_added",
                edge_id=edge.id,
                occurred_at=edge.created_at,
                payload={"edge": edge.model_dump(mode="json")},
            )
            self._upsert_edge(edge)
        return edge

    def add_dependency_suggestion(self, suggestion: DependencySuggestion) -> DependencySuggestion:
        with self._lock, self._conn:
            self._append_suggestion_event(
                event_type="dependency_suggestion_created",
                suggestion=suggestion,
                occurred_at=suggestion.created_at,
            )
            self._upsert_suggestion(suggestion)
        return suggestion

    def update_dependency_suggestion(self, suggestion: DependencySuggestion) -> DependencySuggestion:
        with self._lock, self._conn:
            self._append_suggestion_event(
                event_type=f"dependency_suggestion_{suggestion.decision.value}",
                suggestion=suggestion,
                occurred_at=suggestion.decided_at or suggestion.created_at,
            )
            self._upsert_suggestion(suggestion)
        return suggestion

    def get_dependency_suggestion(self, suggestion_id: str) -> DependencySuggestion:
        row = self._conn.execute(
            "SELECT suggestion_json FROM dependency_suggestions WHERE suggestion_id = ?",
            (suggestion_id,),
        ).fetchone()
        if row is None:
            raise KeyError(suggestion_id)
        return DependencySuggestion.model_validate_json(str(row["suggestion_json"]))

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
            clauses.append("item_id = ?")
            params.append(item_id)
        if decision is not None:
            clauses.append("decision = ?")
            params.append(decision.value)
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if target_id is not None:
            clauses.append("target_id = ?")
            params.append(target_id)
        if created_by is not None:
            clauses.append("created_by = ?")
            params.append(created_by)
        if needs_reverification is not None:
            clauses.append("needs_reverification = ?")
            params.append(int(needs_reverification))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"""
            SELECT suggestion_json
            FROM dependency_suggestions
            {where}
            ORDER BY created_at, suggestion_id
            LIMIT ?
            """,  # noqa: S608
            [*params, limit],
        ).fetchall()
        return [DependencySuggestion.model_validate_json(str(row["suggestion_json"])) for row in rows]

    def list_dependency_suggestion_events(self, suggestion_id: str) -> list[dict[str, object]]:
        rows = self._conn.execute(
            """
            SELECT event_id, event_type, occurred_at, payload_json
            FROM dependency_suggestion_events
            WHERE suggestion_id = ?
            ORDER BY seq
            """,
            (suggestion_id,),
        ).fetchall()
        return [
            {
                "event_id": str(row["event_id"]),
                "event_type": str(row["event_type"]),
                "occurred_at": str(row["occurred_at"]),
                "payload": json.loads(str(row["payload_json"])),
            }
            for row in rows
        ]

    def close_dependency(self, edge_id: str, *, valid_to: datetime) -> DependencyEdge:
        edge = self.get_edge(edge_id)
        closed = edge.model_copy(update={"valid_to": valid_to})
        with self._lock, self._conn:
            self._append_event(
                event_type="dependency_edge_closed",
                edge_id=edge_id,
                occurred_at=valid_to,
                payload={"edge": closed.model_dump(mode="json")},
            )
            self._upsert_edge(closed)
        return closed

    def get_edge(self, edge_id: str) -> DependencyEdge:
        row = self._conn.execute(
            "SELECT edge_json FROM dependency_edges WHERE edge_id = ?",
            (edge_id,),
        ).fetchone()
        if row is None:
            raise KeyError(edge_id)
        return DependencyEdge.model_validate_json(str(row["edge_json"]))

    def get_dependencies(self, item_id: str, *, at: datetime | None = None) -> list[DependencyEdge]:
        return self._select_edges("source_id = ?", [item_id], at=at)

    def get_dependents(self, authority_or_item_id: str, *, at: datetime | None = None) -> list[DependencyEdge]:
        return self._select_edges("target_id = ?", [authority_or_item_id], at=at)

    def impact_edges(self, authority_or_item_id: str) -> list[DependencyEdge]:
        return self.get_dependents(authority_or_item_id)

    def centrality(self, item_or_authority_ids: Iterable[str] | None = None) -> dict[str, int]:
        ids = list(item_or_authority_ids or [])
        if ids:
            placeholders = ",".join("?" for _ in ids)
            rows = self._conn.execute(
                f"""
                SELECT target_id, COUNT(*) AS count
                FROM dependency_edges
                WHERE valid_to IS NULL AND target_id IN ({placeholders})
                GROUP BY target_id
                """,  # noqa: S608
                ids,
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT target_id, COUNT(*) AS count
                FROM dependency_edges
                WHERE valid_to IS NULL
                GROUP BY target_id
                """
            ).fetchall()
        return {str(row["target_id"]): int(row["count"]) for row in rows}

    def subgraph_for_items(self, item_ids: Iterable[str]) -> list[DependencyEdge]:
        ids = list(item_ids)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"""
            SELECT edge_json
            FROM dependency_edges
            WHERE valid_to IS NULL
              AND (source_id IN ({placeholders}) OR target_id IN ({placeholders}))
            ORDER BY source_id, target_id, edge_id
            """,  # noqa: S608
            [*ids, *ids],
        ).fetchall()
        return [DependencyEdge.model_validate_json(str(row["edge_json"])) for row in rows]

    def subgraph_for_scope(
        self,
        *,
        store: KnowledgeStoreProtocol,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> list[DependencyEdge]:
        scoped_items = store.get_many(matter_id=matter_id, client_id=client_id)
        return self.subgraph_for_items(item.id for item in scoped_items)

    def _select_edges(self, clause: str, params: list[Any], *, at: datetime | None) -> list[DependencyEdge]:
        time_clause = "valid_to IS NULL" if at is None else "valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)"
        time_params = [] if at is None else [at.isoformat(), at.isoformat()]
        rows = self._conn.execute(
            f"""
            SELECT edge_json
            FROM dependency_edges
            WHERE {clause} AND {time_clause}
            ORDER BY valid_from, edge_id
            """,  # noqa: S608
            [*params, *time_params],
        ).fetchall()
        return [DependencyEdge.model_validate_json(str(row["edge_json"])) for row in rows]

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
        self._conn.execute(
            """
            INSERT OR IGNORE INTO dependency_edge_events (event_id, event_type, edge_id, occurred_at, payload_json)
            VALUES (?, ?, ?, ?, ?)
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
        self._conn.execute(
            """
            INSERT OR IGNORE INTO dependency_suggestion_events
            (event_id, event_type, suggestion_id, occurred_at, payload_json)
            VALUES (?, ?, ?, ?, ?)
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
        self._conn.execute(
            """
            INSERT INTO dependency_edges
            (edge_id, edge_json, source_id, target_id, edge_type, target_kind,
             valid_from, valid_to, confidence, source_suggestion_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(edge_id) DO UPDATE SET
                edge_json = excluded.edge_json,
                source_id = excluded.source_id,
                target_id = excluded.target_id,
                edge_type = excluded.edge_type,
                target_kind = excluded.target_kind,
                valid_from = excluded.valid_from,
                valid_to = excluded.valid_to,
                confidence = excluded.confidence,
                source_suggestion_id = excluded.source_suggestion_id
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
        self._conn.execute(
            """
            INSERT INTO dependency_suggestions
            (suggestion_id, suggestion_json, item_id, target_id, edge_type, decision, created_at, decided_at,
             source, assertion_type, created_by, idempotency_key, request_sha256, source_document_id,
             source_document_version, needs_reverification, state_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(suggestion_id) DO UPDATE SET
                suggestion_json = excluded.suggestion_json,
                decision = excluded.decision,
                decided_at = excluded.decided_at,
                needs_reverification = excluded.needs_reverification,
                state_version = excluded.state_version
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
                int(suggestion.needs_reverification),
                suggestion.state_version,
            ),
        )


def supersedes_edge(source_id: str, target_id: str, *, created_by: str | None = None) -> DependencyEdge:
    return DependencyEdge(
        source_id=source_id,
        target_id=target_id,
        edge_type=EdgeType.SUPERSEDES,
        target_kind="knowledge_item",
        created_by=created_by,
    )
