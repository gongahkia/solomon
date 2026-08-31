# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sqlite3
from pathlib import Path

from solomon.currency.models import now_utc
from solomon.workflow.models import AuthorityChangeEvent, ReviewTask, ReviewTaskState


class AuthorityEventNotFoundError(KeyError):
    """Raised when an authority event is missing."""


class ReviewTaskNotFoundError(KeyError):
    """Raised when a review task is missing."""


class SQLiteWorkflowStore:
    """Durable authority-event deduplication and human-review task state for local deployments."""

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
                CREATE TABLE IF NOT EXISTS authority_change_events (
                    event_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    authority_id TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    processed_at TEXT,
                    processing_error TEXT,
                    UNIQUE(source_id, idempotency_key)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS review_tasks (
                    task_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    reviewer_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    task_json TEXT NOT NULL,
                    UNIQUE(event_id, item_id)
                )
                """
            )
            authority_columns = {
                str(row["name"]) for row in self._conn.execute("PRAGMA table_info(authority_change_events)").fetchall()
            }
            if "processed_at" not in authority_columns:
                self._conn.execute("ALTER TABLE authority_change_events ADD COLUMN processed_at TEXT")
            if "processing_error" not in authority_columns:
                self._conn.execute("ALTER TABLE authority_change_events ADD COLUMN processing_error TEXT")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_review_tasks_state ON review_tasks(state, created_at)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_review_tasks_reviewer ON review_tasks(reviewer_id, state)"
            )

    def record_authority_event(self, event: AuthorityChangeEvent) -> tuple[AuthorityChangeEvent, bool]:
        existing = self._conn.execute(
            """
            SELECT event_json FROM authority_change_events
            WHERE source_id = ? AND idempotency_key = ?
            """,
            (event.source_id, event.idempotency_key),
        ).fetchone()
        if existing is not None:
            return AuthorityChangeEvent.model_validate_json(str(existing["event_json"])), False
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO authority_change_events
                (event_id, source_id, idempotency_key, authority_id, event_json, received_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.source_id,
                    event.idempotency_key,
                    event.authority_id,
                    event.model_dump_json(),
                    event.received_at.isoformat(),
                ),
            )
        return event, True

    def get_authority_event(self, event_id: str) -> AuthorityChangeEvent:
        row = self._conn.execute(
            "SELECT event_json FROM authority_change_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise AuthorityEventNotFoundError(event_id)
        return AuthorityChangeEvent.model_validate_json(str(row["event_json"]))

    def authority_event_processed(self, event_id: str) -> bool:
        row = self._conn.execute(
            "SELECT processed_at FROM authority_change_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise AuthorityEventNotFoundError(event_id)
        return row["processed_at"] is not None

    def authority_event_processing_error(self, event_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT processing_error FROM authority_change_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise AuthorityEventNotFoundError(event_id)
        return str(row["processing_error"]) if row["processing_error"] is not None else None

    def mark_authority_event_processed(self, event_id: str, *, processed_at: datetime | None = None) -> None:
        timestamp = processed_at or now_utc()
        with self._conn:
            result = self._conn.execute(
                "UPDATE authority_change_events SET processed_at = ?, processing_error = NULL WHERE event_id = ?",
                (timestamp.isoformat(), event_id),
            )
        if result.rowcount != 1:
            raise AuthorityEventNotFoundError(event_id)

    def mark_authority_event_failed(self, event_id: str, *, error: Exception) -> None:
        with self._conn:
            result = self._conn.execute(
                "UPDATE authority_change_events SET processing_error = ? WHERE event_id = ?",
                (error.__class__.__name__, event_id),
            )
        if result.rowcount != 1:
            raise AuthorityEventNotFoundError(event_id)

    def create_review_task(self, task: ReviewTask) -> ReviewTask:
        existing = self._conn.execute(
            "SELECT task_json FROM review_tasks WHERE event_id = ? AND item_id = ?", (task.event_id, task.item_id)
        ).fetchone()
        if existing is not None:
            return ReviewTask.model_validate_json(str(existing["task_json"]))
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO review_tasks
                (task_id, event_id, item_id, state, reviewer_id, created_at, updated_at, task_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.event_id,
                    task.item_id,
                    task.state.value,
                    task.reviewer_id,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                    task.model_dump_json(),
                ),
            )
        return task

    def get_review_task(self, task_id: str) -> ReviewTask:
        row = self._conn.execute("SELECT task_json FROM review_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise ReviewTaskNotFoundError(task_id)
        return ReviewTask.model_validate_json(str(row["task_json"]))

    def list_review_tasks(
        self,
        *,
        reviewer_id: str | None = None,
        state: ReviewTaskState | None = None,
    ) -> list[ReviewTask]:
        clauses: list[str] = []
        params: list[str] = []
        if reviewer_id is not None:
            clauses.append("reviewer_id = ?")
            params.append(reviewer_id)
        if state is not None:
            clauses.append("state = ?")
            params.append(state.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT task_json FROM review_tasks {where} ORDER BY created_at, task_id",  # noqa: S608  # nosec B608
            params,
        ).fetchall()
        return [ReviewTask.model_validate_json(str(row["task_json"])) for row in rows]

    def review_task_state_counts(self) -> dict[str, int]:
        rows = self._conn.execute("SELECT state, COUNT(*) AS count FROM review_tasks GROUP BY state").fetchall()
        return {str(row["state"]): int(row["count"]) for row in rows}

    def assign(self, task_id: str, *, reviewer_id: str, assigned_by: str) -> ReviewTask:
        task = self.get_review_task(task_id)
        if task.state is ReviewTaskState.RESOLVED:
            raise ValueError("resolved review tasks cannot be assigned")
        return self._update_task(
            task.model_copy(
                update={
                    "state": ReviewTaskState.ASSIGNED,
                    "reviewer_id": reviewer_id,
                    "assigned_by": assigned_by,
                    "updated_at": now_utc(),
                }
            )
        )

    def start(self, task_id: str, *, reviewer_id: str) -> ReviewTask:
        task = self.get_review_task(task_id)
        if task.state is ReviewTaskState.RESOLVED:
            raise ValueError("resolved review tasks cannot be started")
        if task.reviewer_id != reviewer_id:
            raise ValueError("only the assigned reviewer can start this task")
        return self._update_task(task.model_copy(update={"state": ReviewTaskState.IN_REVIEW, "updated_at": now_utc()}))

    def resolve(self, task_id: str, *, reviewer_id: str) -> ReviewTask:
        task = self.get_review_task(task_id)
        if task.reviewer_id != reviewer_id:
            raise ValueError("only the assigned reviewer can resolve this task")
        return self._update_task(
            task.model_copy(
                update={"state": ReviewTaskState.RESOLVED, "updated_at": now_utc(), "resolved_at": now_utc()}
            )
        )

    def _update_task(self, task: ReviewTask) -> ReviewTask:
        with self._conn:
            self._conn.execute(
                """
                UPDATE review_tasks
                SET state = ?, reviewer_id = ?, updated_at = ?, task_json = ?
                WHERE task_id = ?
                """,
                (task.state.value, task.reviewer_id, task.updated_at.isoformat(), task.model_dump_json(), task.id),
            )
        return task
