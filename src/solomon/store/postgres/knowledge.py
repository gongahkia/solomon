# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from typing_extensions import Self

from solomon.currency.models import CurrencyState, KnowledgeItem, now_utc
from solomon.store.postgres.connection import (
    ConnectCallable,
    default_connect,
    normalize_schema,
    qualified,
    quote_identifier,
)
from solomon.store.postgres.ddl import create_knowledge_store_schema, create_schema_if_needed
from solomon.store.postgres.serialization import events_to_state, item_from_json, payload_json_text, row_value
from solomon.store.sqlite import ItemNotFoundError, StoreError


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
        self.schema = normalize_schema(schema)
        self._conn = (connect or default_connect)(dsn)
        self.initialize()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def initialize(self) -> None:
        with self._transaction():
            create_schema_if_needed(self._execute, self.schema)
            create_knowledge_store_schema(self._execute, self._table, self._index)

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
        return item_from_json(row_value(row, "item_json"))

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
        return [item_from_json(row_value(row, "item_json")) for row in rows]

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
        return events_to_state(rows)

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
                "event_id": row_value(row, "event_id"),
                "event_type": row_value(row, "event_type"),
                "item_id": row_value(row, "item_id"),
                "occurred_at": row_value(row, "occurred_at"),
                "payload_json": payload_json_text(row_value(row, "payload_json")),
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
        state = events_to_state(rows)

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
            self._execute(f"CREATE SCHEMA IF NOT EXISTS {quote_identifier(self.schema)}")

    def _table(self, name: str) -> str:
        return qualified(self.schema, name)

    def _index(self, name: str) -> str:
        if self.schema is None:
            return quote_identifier(name)
        return quote_identifier(f"{self.schema}_{name}")
