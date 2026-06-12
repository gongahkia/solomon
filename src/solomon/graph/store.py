# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from solomon.graph.models import DependencyEdge, EdgeType
from solomon.store.types import KnowledgeStoreProtocol


class GraphStore:
    """Bi-temporal dependency graph tables co-located with the knowledge SQLite database."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self.initialize()

    def close(self) -> None:
        self._conn.close()

    def initialize(self) -> None:
        with self._conn:
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
                    confidence TEXT NOT NULL
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON dependency_edges(source_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON dependency_edges(target_id)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_edges_current_target ON dependency_edges(target_id, valid_to)"
            )

    def add_dependency(self, edge: DependencyEdge) -> DependencyEdge:
        with self._conn:
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
        with self._conn:
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
        event_id = f"{edge_id}:{event_type}:{occurred_at.isoformat()}:{len(json.dumps(payload, sort_keys=True))}"
        self._conn.execute(
            """
            INSERT INTO dependency_edge_events (event_id, event_type, edge_id, occurred_at, payload_json)
            VALUES (?, ?, ?, ?, ?)
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
        self._conn.execute(
            """
            INSERT INTO dependency_edges
            (edge_id, edge_json, source_id, target_id, edge_type, target_kind,
             valid_from, valid_to, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(edge_id) DO UPDATE SET
                edge_json = excluded.edge_json,
                source_id = excluded.source_id,
                target_id = excluded.target_id,
                edge_type = excluded.edge_type,
                target_kind = excluded.target_kind,
                valid_from = excluded.valid_from,
                valid_to = excluded.valid_to,
                confidence = excluded.confidence
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


def supersedes_edge(source_id: str, target_id: str, *, created_by: str | None = None) -> DependencyEdge:
    return DependencyEdge(
        source_id=source_id,
        target_id=target_id,
        edge_type=EdgeType.SUPERSEDES,
        target_kind="knowledge_item",
        created_by=created_by,
    )
