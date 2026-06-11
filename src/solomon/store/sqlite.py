# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from typing_extensions import Self

from solomon.currency.models import CurrencyState, KnowledgeItem, now_utc


class StoreError(RuntimeError):
    """Base exception for store failures."""


class ItemNotFoundError(StoreError):
    """Raised when a requested knowledge item is missing."""


class SQLiteKnowledgeStore:
    """Append-only SQLite event store with a materialised current-state table."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self.initialize()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def initialize(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_items (
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
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_items_state ON knowledge_items(currency_state)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_items_scope ON knowledge_items(matter_id, client_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_events_time ON knowledge_events(occurred_at, seq)"
            )

    def write_item(self, item: KnowledgeItem) -> KnowledgeItem:
        with self._conn:
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
        with self._conn:
            self._append_event(
                event_type=event_type,
                item_id=item.id,
                occurred_at=occurred_at or now_utc(),
                payload={"item": item.model_dump(mode="json")},
            )
            self._upsert_current(item)
        return item

    def get_item(self, item_id: str) -> KnowledgeItem:
        row = self._conn.execute(
            "SELECT item_json FROM knowledge_items WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise ItemNotFoundError(item_id)
        return KnowledgeItem.model_validate_json(str(row["item_json"]))

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
            placeholders = ",".join("?" for _ in ids)
            clauses.append(f"item_id IN ({placeholders})")
            params.extend(ids)
        if include_states is not None:
            states = [state.value for state in include_states]
            if not states:
                return []
            placeholders = ",".join("?" for _ in states)
            clauses.append(f"currency_state IN ({placeholders})")
            params.extend(states)
        if matter_id is not None:
            clauses.append("matter_id = ?")
            params.append(matter_id)
        if client_id is not None:
            clauses.append("client_id = ?")
            params.append(client_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT item_json FROM knowledge_items {where} ORDER BY ingested_at, item_id",  # noqa: S608
            params,
        ).fetchall()
        return [KnowledgeItem.model_validate_json(str(row["item_json"])) for row in rows]

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

        with self._conn:
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
        cutoff = timestamp.isoformat()
        rows = self._conn.execute(
            """
            SELECT event_type, payload_json
            FROM knowledge_events
            WHERE occurred_at <= ?
            ORDER BY occurred_at, seq
            """,
            (cutoff,),
        ).fetchall()
        state: dict[str, KnowledgeItem] = {}
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            event_type = str(row["event_type"])
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

    def snapshot(self, destination: Path | str) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        rows = self._conn.execute(
            """
            SELECT event_id, event_type, item_id, occurred_at, payload_json
            FROM knowledge_events
            ORDER BY seq
            """
        ).fetchall()
        payload = {
            "schema": "solomon.snapshot.v1",
            "events": [dict(row) for row in rows],
        }
        target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return target

    @classmethod
    def restore(cls, snapshot: Path | str, destination_db: Path | str) -> SQLiteKnowledgeStore:
        target = cls(destination_db)
        raw = json.loads(Path(snapshot).read_text(encoding="utf-8"))
        if raw.get("schema") != "solomon.snapshot.v1":
            raise StoreError("unsupported snapshot schema")
        with target._conn:
            for event in raw.get("events", []):
                target._conn.execute(
                    """
                    INSERT OR IGNORE INTO knowledge_events
                    (event_id, event_type, item_id, occurred_at, payload_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        event["event_id"],
                        event["event_type"],
                        event["item_id"],
                        event["occurred_at"],
                        event["payload_json"],
                    ),
                )
            target.rebuild_current_state()
        return target

    def rebuild_current_state(self) -> None:
        rows = self._conn.execute(
            "SELECT event_type, payload_json FROM knowledge_events ORDER BY occurred_at, seq"
        ).fetchall()
        state: dict[str, KnowledgeItem] = {}
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            event_type = str(row["event_type"])
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
        self._conn.execute("DROP TABLE IF EXISTS knowledge_items_rebuild")
        self._conn.execute(
            """
            CREATE TEMP TABLE knowledge_items_rebuild (
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
        for item in state.values():
            self._upsert_current(item, table="knowledge_items_rebuild")
        self._conn.execute("DROP TABLE knowledge_items")
        self._conn.execute("ALTER TABLE knowledge_items_rebuild RENAME TO knowledge_items")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_items_state ON knowledge_items(currency_state)")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_items_scope ON knowledge_items(matter_id, client_id)"
        )

    def pragma(self, name: str) -> Any:
        row = self._conn.execute(f"PRAGMA {name}").fetchone()  # noqa: S608
        if row is None:
            return None
        return row[0]

    def _append_event(
        self,
        *,
        event_type: str,
        item_id: str,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> None:
        event_id = f"{item_id}:{event_type}:{occurred_at.isoformat()}:{len(json.dumps(payload, sort_keys=True))}"
        self._conn.execute(
            """
            INSERT INTO knowledge_events (event_id, event_type, item_id, occurred_at, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event_id,
                event_type,
                item_id,
                occurred_at.isoformat(),
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
            ),
        )

    def _upsert_current(self, item: KnowledgeItem, *, table: str = "knowledge_items") -> None:
        if table not in {"knowledge_items", "knowledge_items_rebuild"}:
            raise StoreError(f"unsupported current-state table: {table}")
        self._conn.execute(
            f"""
            INSERT INTO {table}
            (item_id, schema_version, item_json, currency_state, valid_from, valid_to, ingested_at,
             successor_id, matter_id, client_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_id) DO UPDATE SET
                schema_version = excluded.schema_version,
                item_json = excluded.item_json,
                currency_state = excluded.currency_state,
                valid_from = excluded.valid_from,
                valid_to = excluded.valid_to,
                ingested_at = excluded.ingested_at,
                successor_id = excluded.successor_id,
                matter_id = excluded.matter_id,
                client_id = excluded.client_id
            """,  # noqa: S608
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
