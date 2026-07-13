# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from typing_extensions import Self

from solomon.currency.models import CurrencyState, KnowledgeItem, is_v01_knowledge_item_payload, now_utc
from solomon.events import DomainEventEnvelope
from solomon.store.migrations import apply_sqlite_migrations, sqlite_knowledge_store_migrations
from solomon.store.outbox import OutboxRecord
from solomon.store.types import KnowledgeEvent


class StoreError(RuntimeError):
    """Base exception for store failures."""


class ItemNotFoundError(StoreError):
    """Raised when a requested knowledge item is missing."""


class OutboxEventNotFoundError(StoreError):
    """Raised when a requested outbox event is missing."""


class SQLiteKnowledgeStore:
    """Append-only SQLite event store with a materialised current-state table."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._execute_locked_retry("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self.initialize()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def initialize(self) -> None:
        apply_sqlite_migrations(self._conn, sqlite_knowledge_store_migrations())
        self._migrate_v01_current_items()

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
                "knowledge_item_contradiction_flagged",
                "knowledge_item_indexed",
                "knowledge_item_contested",
                "knowledge_item_affirmed",
                "knowledge_item_correction_affirmed",
                "knowledge_item_pinned",
                "verification_lifecycle_assigned",
                "verification_lifecycle_in_review",
                "verification_lifecycle_completed",
            }:
                item = KnowledgeItem.model_validate(payload["item"])
                state[item.id] = item
            elif event_type == "knowledge_item_superseded":
                predecessor = KnowledgeItem.model_validate(payload["predecessor"])
                successor = KnowledgeItem.model_validate(payload["successor"])
                state[predecessor.id] = predecessor
                state[successor.id] = successor
        return sorted(state.values(), key=lambda item: (item.ingested_at, item.id))

    def list_events(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        event_types: set[str] | None = None,
    ) -> list[KnowledgeEvent]:
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("occurred_at >= ?")
            params.append(since.isoformat())
        if until is not None:
            clauses.append("occurred_at <= ?")
            params.append(until.isoformat())
        if event_types is not None:
            types = sorted(event_types)
            if not types:
                return []
            placeholders = ",".join("?" for _ in types)
            clauses.append(f"event_type IN ({placeholders})")
            params.extend(types)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"""
            SELECT seq, event_type, item_id, occurred_at, payload_json
            FROM knowledge_events
            {where}
            ORDER BY occurred_at, seq
            """,  # noqa: S608
            params,
        ).fetchall()
        return [
            KnowledgeEvent(
                seq=int(row["seq"]),
                event_type=str(row["event_type"]),
                item_id=str(row["item_id"]),
                occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
                payload=json.loads(str(row["payload_json"])),
            )
            for row in rows
        ]

    def pending_outbox_events(
        self,
        *,
        limit: int = 100,
        available_before: datetime | None = None,
    ) -> list[OutboxRecord]:
        if limit < 1:
            raise ValueError("limit must be positive")
        cutoff = (available_before or now_utc()).isoformat()
        rows = self._conn.execute(
            """
            SELECT event_json, available_at, delivered_at, delivery_attempts, last_error
            FROM outbox_events
            WHERE delivered_at IS NULL AND available_at <= ?
            ORDER BY available_at, event_id
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
        return [self._outbox_record(row) for row in rows]

    def mark_outbox_delivered(self, event_id: str, *, delivered_at: datetime | None = None) -> OutboxRecord:
        row = self._conn.execute(
            "SELECT event_json, available_at, delivered_at, delivery_attempts, last_error "
            "FROM outbox_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise OutboxEventNotFoundError(event_id)
        recorded = self._outbox_record(row)
        if recorded.delivered_at is not None:
            return recorded
        completed_at = delivered_at or now_utc()
        with self._conn:
            self._conn.execute(
                """
                UPDATE outbox_events
                SET delivered_at = ?, delivery_attempts = delivery_attempts + 1, last_error = NULL
                WHERE event_id = ?
                """,
                (completed_at.isoformat(), event_id),
            )
        return recorded.model_copy(
            update={"delivered_at": completed_at, "delivery_attempts": recorded.delivery_attempts + 1}
        )

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
            "outbox_events": [
                dict(row)
                for row in self._conn.execute(
                    """
                    SELECT event_id, event_type, available_at, delivered_at, delivery_attempts, last_error, event_json
                    FROM outbox_events ORDER BY available_at, event_id
                    """
                ).fetchall()
            ],
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
            for event in raw.get("outbox_events", []):
                target._conn.execute(
                    """
                    INSERT OR IGNORE INTO outbox_events
                    (event_id, event_type, available_at, delivered_at, delivery_attempts, last_error, event_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event["event_id"],
                        event["event_type"],
                        event["available_at"],
                        event["delivered_at"],
                        event["delivery_attempts"],
                        event["last_error"],
                        event["event_json"],
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
                "knowledge_item_contradiction_flagged",
                "knowledge_item_indexed",
                "knowledge_item_contested",
                "knowledge_item_affirmed",
                "knowledge_item_correction_affirmed",
                "knowledge_item_pinned",
                "verification_lifecycle_assigned",
                "verification_lifecycle_in_review",
                "verification_lifecycle_completed",
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

    def _execute_locked_retry(self, sql: str) -> sqlite3.Cursor:
        for attempt in range(6):
            try:
                return self._conn.execute(sql)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
        raise StoreError("unreachable SQLite retry state")

    def _migrate_v01_current_items(self) -> None:
        rows = self._conn.execute("SELECT item_json FROM knowledge_items").fetchall()
        with self._conn:
            for row in rows:
                payload = json.loads(str(row["item_json"]))
                if not is_v01_knowledge_item_payload(payload):
                    continue
                self._upsert_current(KnowledgeItem.model_validate(payload))

    def _append_event(
        self,
        *,
        event_type: str,
        item_id: str,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> None:
        event = self._domain_event(event_type=event_type, item_id=item_id, occurred_at=occurred_at, payload=payload)
        self._conn.execute(
            """
            INSERT INTO knowledge_events (event_id, event_type, item_id, occurred_at, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event_type,
                item_id,
                occurred_at.isoformat(),
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
            ),
        )
        self._enqueue_outbox(event)

    @staticmethod
    def _domain_event(
        *,
        event_type: str,
        item_id: str,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> DomainEventEnvelope:
        payload_sha256 = DomainEventEnvelope.payload_digest(payload)
        identity = f"knowledge_item:{item_id}:{event_type}:{occurred_at.isoformat()}:{payload_sha256}"
        event_id = sha256(identity.encode("utf-8")).hexdigest()
        return DomainEventEnvelope(
            event_id=event_id,
            event_type=event_type,
            aggregate_type="knowledge_item",
            aggregate_id=item_id,
            actor_id="system:knowledge-store",
            correlation_id=f"knowledge_item:{item_id}",
            idempotency_key=event_id,
            occurred_at=occurred_at,
            payload=payload,
        )

    def _enqueue_outbox(self, event: DomainEventEnvelope) -> None:
        record = OutboxRecord(event=event, available_at=event.occurred_at)
        self._conn.execute(
            """
            INSERT INTO outbox_events
            (event_id, event_type, available_at, delivered_at, delivery_attempts, last_error, event_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.event_type,
                record.available_at.isoformat(),
                None,
                record.delivery_attempts,
                None,
                event.model_dump_json(),
            ),
        )

    @staticmethod
    def _outbox_record(row: sqlite3.Row) -> OutboxRecord:
        return OutboxRecord(
            event=DomainEventEnvelope.model_validate_json(str(row["event_json"])),
            available_at=datetime.fromisoformat(str(row["available_at"])),
            delivered_at=datetime.fromisoformat(str(row["delivered_at"])) if row["delivered_at"] else None,
            delivery_attempts=int(row["delivery_attempts"]),
            last_error=str(row["last_error"]) if row["last_error"] is not None else None,
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
