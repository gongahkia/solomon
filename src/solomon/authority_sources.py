# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins
import sqlite3
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path

from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.contracts import AuthoritySource, SyncCheckpoint
from solomon.currency.models import _ensure_aware_utc, now_utc
from solomon.events import DomainEventEnvelope
from solomon.store.outbox import OutboxRecord


class AuthoritySourceNotFoundError(KeyError):
    pass


class AuthorityPollDeadLetter(SolomonModel):
    record: OutboxRecord
    dead_lettered_at: datetime
    reason: str = Field(min_length=1)


class SQLiteAuthoritySourceRegistry:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.initialize()

    def close(self) -> None:
        self._conn.close()

    def initialize(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS authority_sources (
                    source_id TEXT PRIMARY KEY,
                    canonical_namespace TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    source_json TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_authority_sources_namespace "
                "ON authority_sources(canonical_namespace, enabled)"
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS authority_poll_state (
                    source_id TEXT PRIMARY KEY,
                    checkpoint_json TEXT,
                    next_due_at TEXT,
                    last_polled_at TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS authority_poll_outbox (
                    event_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    delivered_at TEXT,
                    delivery_attempts INTEGER NOT NULL,
                    last_error TEXT,
                    dead_lettered_at TEXT,
                    dead_letter_reason TEXT,
                    event_json TEXT NOT NULL
                )
                """
            )
            columns = {
                str(row["name"]) for row in self._conn.execute("PRAGMA table_info(authority_poll_outbox)").fetchall()
            }
            if "dead_lettered_at" not in columns:
                self._conn.execute("ALTER TABLE authority_poll_outbox ADD COLUMN dead_lettered_at TEXT")
            if "dead_letter_reason" not in columns:
                self._conn.execute("ALTER TABLE authority_poll_outbox ADD COLUMN dead_letter_reason TEXT")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_authority_poll_outbox_pending "
                "ON authority_poll_outbox(delivered_at, available_at, event_id)"
            )

    def register(self, source: AuthoritySource) -> AuthoritySource:
        existing = self._conn.execute(
            "SELECT source_json FROM authority_sources WHERE source_id = ?",
            (source.id,),
        ).fetchone()
        if existing is not None:
            persisted = AuthoritySource.model_validate_json(str(existing["source_json"]))
            if persisted == source:
                return persisted
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO authority_sources (source_id, canonical_namespace, enabled, source_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    canonical_namespace = excluded.canonical_namespace,
                    enabled = excluded.enabled,
                    source_json = excluded.source_json
                """,
                (source.id, source.canonical_namespace, int(source.enabled), source.model_dump_json()),
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO authority_poll_state (source_id) VALUES (?)",
                (source.id,),
            )
        return source

    def get(self, source_id: str) -> AuthoritySource:
        row = self._conn.execute(
            "SELECT source_json FROM authority_sources WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if row is None:
            raise AuthoritySourceNotFoundError(source_id)
        return AuthoritySource.model_validate_json(str(row["source_json"]))

    def list(self, *, enabled: bool | None = None) -> builtins.list[AuthoritySource]:
        if enabled is None:
            rows = self._conn.execute("SELECT source_json FROM authority_sources ORDER BY source_id").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT source_json FROM authority_sources WHERE enabled = ? ORDER BY source_id",
                (int(enabled),),
            ).fetchall()
        return [AuthoritySource.model_validate_json(str(row["source_json"])) for row in rows]

    def get_poll_checkpoint(self, source_id: str) -> SyncCheckpoint | None:
        self.get(source_id)
        row = self._conn.execute(
            "SELECT checkpoint_json FROM authority_poll_state WHERE source_id = ?", (source_id,)
        ).fetchone()
        if row is None or row["checkpoint_json"] is None:
            return None
        return SyncCheckpoint.model_validate_json(str(row["checkpoint_json"]))

    def schedule_due_polls(self, *, as_of: datetime | None = None) -> builtins.list[OutboxRecord]:
        due_at = _ensure_aware_utc(as_of or now_utc())
        scheduled: builtins.list[OutboxRecord] = []
        for source in self.list(enabled=True):
            record = self._schedule_source_poll(source, due_at)
            if record is not None:
                scheduled.append(record)
        return scheduled

    def pending_poll_events(
        self,
        *,
        limit: int = 100,
        available_before: datetime | None = None,
    ) -> builtins.list[OutboxRecord]:
        if limit < 1:
            raise ValueError("limit must be positive")
        cutoff = _ensure_aware_utc(available_before or now_utc()).isoformat()
        rows = self._conn.execute(
            """
            SELECT event_json, available_at, delivered_at, delivery_attempts, last_error
            FROM authority_poll_outbox
            WHERE delivered_at IS NULL AND dead_lettered_at IS NULL AND available_at <= ?
            ORDER BY available_at, event_id LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
        return [self._outbox_record(row) for row in rows]

    def complete_poll(
        self,
        event_id: str,
        *,
        checkpoint: SyncCheckpoint | None,
        completed_at: datetime | None = None,
    ) -> OutboxRecord:
        completed = _ensure_aware_utc(completed_at or now_utc())
        with self._conn:
            row = self._conn.execute(
                """
                SELECT source_id, event_json, available_at, delivered_at, delivery_attempts, last_error
                FROM authority_poll_outbox WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                raise AuthorityPollEventNotFoundError(event_id)
            record = self._outbox_record(row)
            if record.delivered_at is not None:
                return record
            self._conn.execute(
                """
                UPDATE authority_poll_outbox
                SET delivered_at = ?, delivery_attempts = delivery_attempts + 1, last_error = NULL
                WHERE event_id = ?
                """,
                (completed.isoformat(), event_id),
            )
            if checkpoint is not None:
                if checkpoint.source_id != str(row["source_id"]):
                    raise ValueError("poll checkpoint source does not match outbox source")
                self._conn.execute(
                    """
                    UPDATE authority_poll_state
                    SET checkpoint_json = ?, last_polled_at = ? WHERE source_id = ?
                    """,
                    (checkpoint.model_dump_json(), completed.isoformat(), str(row["source_id"])),
                )
            else:
                self._conn.execute(
                    "UPDATE authority_poll_state SET last_polled_at = ? WHERE source_id = ?",
                    (completed.isoformat(), str(row["source_id"])),
                )
        return record.model_copy(update={"delivered_at": completed, "delivery_attempts": record.delivery_attempts + 1})

    def record_poll_failure(
        self,
        event_id: str,
        *,
        error: str,
        retry_at: datetime | None = None,
        dead_letter: bool = False,
        failed_at: datetime | None = None,
    ) -> OutboxRecord:
        failure_at = _ensure_aware_utc(failed_at or now_utc())
        with self._conn:
            row = self._conn.execute(
                """
                SELECT event_json, available_at, delivered_at, delivery_attempts, last_error
                FROM authority_poll_outbox WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                raise AuthorityPollEventNotFoundError(event_id)
            record = self._outbox_record(row)
            if record.delivered_at is not None:
                return record
            available_at = (
                _ensure_aware_utc(retry_at).isoformat() if retry_at is not None else record.available_at.isoformat()
            )
            self._conn.execute(
                """
                UPDATE authority_poll_outbox
                SET delivery_attempts = delivery_attempts + 1, last_error = ?, available_at = ?,
                    dead_lettered_at = ?, dead_letter_reason = ?
                WHERE event_id = ?
                """,
                (
                    error[:500],
                    available_at,
                    failure_at.isoformat() if dead_letter else None,
                    error[:500] if dead_letter else None,
                    event_id,
                ),
            )
        return record.model_copy(
            update={
                "available_at": datetime.fromisoformat(available_at),
                "delivery_attempts": record.delivery_attempts + 1,
                "last_error": error[:500],
            }
        )

    def dead_letter_poll_events(self, *, limit: int = 100) -> builtins.list[AuthorityPollDeadLetter]:
        if limit < 1:
            raise ValueError("limit must be positive")
        rows = self._conn.execute(
            """
            SELECT event_json, available_at, delivered_at, delivery_attempts, last_error,
                   dead_lettered_at, dead_letter_reason
            FROM authority_poll_outbox
            WHERE dead_lettered_at IS NOT NULL
            ORDER BY dead_lettered_at, event_id LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            AuthorityPollDeadLetter(
                record=self._outbox_record(row),
                dead_lettered_at=datetime.fromisoformat(str(row["dead_lettered_at"])),
                reason=str(row["dead_letter_reason"]),
            )
            for row in rows
        ]

    def poll_queue_depths(self) -> dict[str, int]:
        row = self._conn.execute(
            """
            SELECT
                SUM(CASE WHEN delivered_at IS NULL AND dead_lettered_at IS NULL THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN dead_lettered_at IS NOT NULL THEN 1 ELSE 0 END) AS dead_letter
            FROM authority_poll_outbox
            """
        ).fetchone()
        return {"pending": int(row["pending"] or 0), "dead_letter": int(row["dead_letter"] or 0)}

    def requeue_dead_letter(self, event_id: str, *, available_at: datetime | None = None) -> OutboxRecord:
        retry_at = _ensure_aware_utc(available_at or now_utc())
        with self._conn:
            row = self._conn.execute(
                """
                SELECT event_json, available_at, delivered_at, delivery_attempts, last_error, dead_lettered_at
                FROM authority_poll_outbox WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                raise AuthorityPollEventNotFoundError(event_id)
            if row["dead_lettered_at"] is None:
                raise ValueError("authority poll event is not dead-lettered")
            record = self._outbox_record(row)
            self._conn.execute(
                """
                UPDATE authority_poll_outbox
                SET available_at = ?, delivery_attempts = 0, last_error = NULL,
                    dead_lettered_at = NULL, dead_letter_reason = NULL
                WHERE event_id = ?
                """,
                (retry_at.isoformat(), event_id),
            )
        return record.model_copy(update={"available_at": retry_at, "delivery_attempts": 0, "last_error": None})

    def _schedule_source_poll(self, source: AuthoritySource, due_at: datetime) -> OutboxRecord | None:
        with self._conn:
            pending = self._conn.execute(
                "SELECT 1 FROM authority_poll_outbox WHERE source_id = ? AND delivered_at IS NULL LIMIT 1",
                (source.id,),
            ).fetchone()
            if pending is not None:
                return None
            state = self._conn.execute(
                "SELECT next_due_at FROM authority_poll_state WHERE source_id = ?", (source.id,)
            ).fetchone()
            if state is None:
                self._conn.execute("INSERT INTO authority_poll_state (source_id) VALUES (?)", (source.id,))
                next_due_at = None
            else:
                next_due_at = state["next_due_at"]
            if next_due_at is not None and datetime.fromisoformat(str(next_due_at)) > due_at:
                return None
            identity = f"authority_poll:{source.id}:{due_at.isoformat()}"
            event_id = sha256(identity.encode("utf-8")).hexdigest()
            event = DomainEventEnvelope(
                event_id=event_id,
                event_type="authority_source_poll_requested",
                aggregate_type="authority_source",
                aggregate_id=source.id,
                actor_id="system:authority-poller",
                correlation_id=identity,
                idempotency_key=event_id,
                occurred_at=due_at,
                payload={"source_id": source.id, "scheduled_at": due_at.isoformat()},
            )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO authority_poll_outbox
                (event_id, source_id, available_at, delivered_at, delivery_attempts, last_error,
                 dead_lettered_at, dead_letter_reason, event_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (event.event_id, source.id, due_at.isoformat(), None, 0, None, None, None, event.model_dump_json()),
            )
            self._conn.execute(
                "UPDATE authority_poll_state SET next_due_at = ? WHERE source_id = ?",
                ((due_at + timedelta(seconds=source.poll_schedule.interval_seconds)).isoformat(), source.id),
            )
        return OutboxRecord(event=event, available_at=due_at)

    @staticmethod
    def _outbox_record(row: sqlite3.Row) -> OutboxRecord:
        return OutboxRecord(
            event=DomainEventEnvelope.model_validate_json(str(row["event_json"])),
            available_at=datetime.fromisoformat(str(row["available_at"])),
            delivered_at=datetime.fromisoformat(str(row["delivered_at"])) if row["delivered_at"] else None,
            delivery_attempts=int(row["delivery_attempts"]),
            last_error=str(row["last_error"]) if row["last_error"] is not None else None,
        )


class AuthorityPollEventNotFoundError(KeyError):
    pass


__all__ = [
    "AuthorityPollEventNotFoundError",
    "AuthorityPollDeadLetter",
    "AuthoritySourceNotFoundError",
    "SQLiteAuthoritySourceRegistry",
]
