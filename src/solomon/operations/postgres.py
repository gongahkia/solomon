# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
from builtins import list as builtins_list
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from solomon.currency.models import now_utc
from solomon.operations.models import (
    OperationHistoryEntry,
    OperationPhase,
    OperationRecord,
    OperationScope,
    OperationStatus,
    OperationType,
)
from solomon.operations.store import OperationConflictError, OperationNotFoundError
from solomon.store.migrations import apply_postgres_migrations, operation_store_migrations
from solomon.store.postgres.connection import ConnectCallable, default_connect, normalize_schema, quote_identifier


class PostgresOperationStore:
    """PostgreSQL operation journal with `SKIP LOCKED` claims for concurrent workers."""

    def __init__(self, dsn: str, *, connect: ConnectCallable | None = None, schema: str | None = None) -> None:
        self.dsn = dsn
        self.schema = normalize_schema(schema)
        self._conn = (connect or default_connect)(dsn)
        self.initialize()

    def close(self) -> None:
        self._conn.close()

    def initialize(self) -> None:
        with self._transaction():
            if self.schema is not None:
                self._execute(f"CREATE SCHEMA IF NOT EXISTS {quote_identifier(self.schema)}")
                # The store keeps one connection for its lifetime.  `SET LOCAL` would
                # revert on this transaction's commit and leave subsequent unqualified
                # journal queries pointed at the caller's default schema.
                self._execute(f"SET search_path TO {quote_identifier(self.schema)}")
            apply_postgres_migrations(self._execute, operation_store_migrations())

    def create(self, operation: OperationRecord) -> tuple[OperationRecord, bool]:
        existing = self._by_idempotency(operation.operation_type, operation.scope, operation.idempotency_key)
        if existing is not None:
            if _immutable_fingerprint(existing) != _immutable_fingerprint(operation):
                raise OperationConflictError("idempotency key was already used for a different operation")
            return existing, False
        with self._transaction():
            self._execute(
                """
                INSERT INTO knowledge_operations
                (operation_id, operation_type, scope_key, tenant_id, matter_id, client_id, idempotency_key,
                 status, phase, state_version, attempt_count, next_eligible_retry_at, lease_owner, lease_expires_at,
                 created_at, updated_at, operation_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                _operation_values(operation),
            )
            self._append_history(
                OperationHistoryEntry(
                    operation_id=operation.id,
                    state_version=operation.state_version,
                    event="created",
                    status=operation.status,
                    phase=operation.phase,
                    occurred_at=operation.created_at,
                    actor_id=operation.actor_id,
                )
            )
        return operation, True

    def get(self, operation_id: str) -> OperationRecord:
        row = self._execute(
            "SELECT operation_json FROM knowledge_operations WHERE operation_id = %s",
            (operation_id,),
        ).fetchone()
        if row is None:
            raise OperationNotFoundError(operation_id)
        return OperationRecord.model_validate_json(_value(row, "operation_json", 0))

    def list(
        self,
        *,
        scope: OperationScope | None = None,
        statuses: set[OperationStatus] | None = None,
        limit: int = 100,
    ) -> list[OperationRecord]:
        if limit < 1 or limit > 10_000:
            raise ValueError("limit must be between 1 and 10000")
        clauses: list[str] = []
        params: list[Any] = []
        if scope is not None:
            clauses.append("scope_key = %s")
            params.append(scope.key)
        if statuses is not None:
            if not statuses:
                return []
            clauses.append(f"status IN ({','.join('%s' for _ in statuses)})")
            params.extend(sorted(status.value for status in statuses))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._execute(
            f"""
            SELECT operation_json FROM knowledge_operations {where}
            ORDER BY created_at, operation_id LIMIT %s
            """,  # noqa: S608
            tuple([*params, limit]),
        ).fetchall()
        return [OperationRecord.model_validate_json(_value(row, "operation_json", 0)) for row in rows]

    def history(self, operation_id: str) -> builtins_list[OperationHistoryEntry]:
        self.get(operation_id)
        rows = self._execute(
            """
            SELECT history_json FROM knowledge_operation_history
            WHERE operation_id = %s ORDER BY state_version
            """,
            (operation_id,),
        ).fetchall()
        return [OperationHistoryEntry.model_validate_json(_value(row, "history_json", 0)) for row in rows]

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 30,
        now: datetime | None = None,
        scope: OperationScope | None = None,
    ) -> OperationRecord | None:
        if not worker_id or lease_seconds < 1:
            raise ValueError("worker ID and positive lease duration are required")
        timestamp = now or now_utc()
        clauses = [
            "((status IN ('queued', 'retrying') AND "
            "(next_eligible_retry_at IS NULL OR next_eligible_retry_at <= %s)) "
            "OR (status = 'claimed' AND lease_expires_at IS NOT NULL AND lease_expires_at <= %s))",
        ]
        params: list[Any] = [timestamp.isoformat(), timestamp.isoformat()]
        if scope is not None:
            clauses.append("scope_key = %s")
            params.append(scope.key)
        with self._transaction():
            row = self._execute(
                f"""
                SELECT operation_json FROM knowledge_operations
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at, operation_id FOR UPDATE SKIP LOCKED LIMIT 1
                """,  # noqa: S608
                tuple(params),
            ).fetchone()
            if row is None:
                return None
            current = OperationRecord.model_validate_json(_value(row, "operation_json", 0))
            reclaimed = current.status is OperationStatus.CLAIMED
            claimed = current.with_transition(
                status=OperationStatus.CLAIMED,
                phase=current.phase,
                attempt_count=current.attempt_count + 1,
                failure_category=None,
                diagnostic=None,
                next_eligible_retry_at=None,
                lease_owner=worker_id,
                lease_expires_at=timestamp + timedelta(seconds=lease_seconds),
                updated_at=timestamp,
            )
            self._replace(current, claimed)
            self._append_history(
                OperationHistoryEntry(
                    operation_id=claimed.id,
                    state_version=claimed.state_version,
                    event="reclaimed" if reclaimed else "claimed",
                    status=claimed.status,
                    phase=claimed.phase,
                    occurred_at=timestamp,
                    actor_id=worker_id,
                )
            )
            return claimed

    def checkpoint(
        self,
        operation_id: str,
        *,
        worker_id: str,
        phase: OperationPhase,
        result_entity_id: str | None = None,
        result_edge_id: str | None = None,
        audit_entry_hash: str | None = None,
        now: datetime | None = None,
    ) -> OperationRecord:
        current = self._claimed_by(operation_id, worker_id)
        updated = current.with_transition(
            status=OperationStatus.CLAIMED,
            phase=phase,
            checkpoint=phase,
            lease_owner=current.lease_owner,
            lease_expires_at=current.lease_expires_at,
            result_entity_id=result_entity_id,
            result_edge_id=result_edge_id,
            audit_entry_hashes=_append_distinct(current.audit_entry_hashes, audit_entry_hash),
            updated_at=now or now_utc(),
        )
        self._write_transition(current, updated, event="checkpoint", actor_id=worker_id)
        return updated

    def complete(
        self,
        operation_id: str,
        *,
        worker_id: str,
        result_entity_id: str | None = None,
        result_edge_id: str | None = None,
        audit_entry_hash: str | None = None,
        now: datetime | None = None,
    ) -> OperationRecord:
        current = self._claimed_by(operation_id, worker_id)
        completed = current.with_transition(
            status=OperationStatus.COMPLETED,
            checkpoint=OperationPhase.AUDIT,
            lease_owner=None,
            lease_expires_at=None,
            result_entity_id=result_entity_id,
            result_edge_id=result_edge_id,
            audit_entry_hashes=_append_distinct(current.audit_entry_hashes, audit_entry_hash),
            updated_at=now or now_utc(),
        )
        self._write_transition(current, completed, event="completed", actor_id=worker_id)
        return completed

    def retry(
        self,
        operation_id: str,
        *,
        worker_id: str,
        retry_at: datetime,
        failure_category: str,
        diagnostic: str,
        maximum_attempts: int,
        now: datetime | None = None,
    ) -> OperationRecord:
        current = self._claimed_by(operation_id, worker_id)
        terminal = current.attempt_count >= maximum_attempts
        updated = current.with_transition(
            status=OperationStatus.TERMINAL_FAILED if terminal else OperationStatus.RETRYING,
            lease_owner=None,
            lease_expires_at=None,
            failure_category=failure_category,
            diagnostic=_safe_diagnostic(diagnostic),
            next_eligible_retry_at=None if terminal else retry_at,
            updated_at=now or now_utc(),
        )
        self._write_transition(
            current,
            updated,
            event="terminal_failed" if terminal else "retry_scheduled",
            actor_id=worker_id,
            detail=updated.diagnostic,
        )
        return updated

    def require_operator(
        self,
        operation_id: str,
        *,
        worker_id: str,
        failure_category: str,
        diagnostic: str,
    ) -> OperationRecord:
        current = self._claimed_by(operation_id, worker_id)
        updated = current.with_transition(
            status=OperationStatus.OPERATOR_REQUIRED,
            lease_owner=None,
            lease_expires_at=None,
            failure_category=failure_category,
            diagnostic=_safe_diagnostic(diagnostic),
            next_eligible_retry_at=None,
        )
        self._write_transition(
            current,
            updated,
            event="operator_required",
            actor_id=worker_id,
            detail=updated.diagnostic,
        )
        return updated

    def manual_retry(self, operation_id: str, *, actor_id: str, now: datetime | None = None) -> OperationRecord:
        current = self.get(operation_id)
        if current.status not in {OperationStatus.TERMINAL_FAILED, OperationStatus.OPERATOR_REQUIRED}:
            raise OperationConflictError("only terminal operations can be manually retried")
        timestamp = now or now_utc()
        queued = current.model_copy(
            update={
                "status": OperationStatus.QUEUED,
                "failure_category": None,
                "diagnostic": None,
                "next_eligible_retry_at": timestamp,
                "state_version": current.state_version + 1,
                "updated_at": timestamp,
            }
        )
        self._write_transition(current, queued, event="manual_retry", actor_id=actor_id)
        return queued

    def counts(self, *, now: datetime | None = None, scope: OperationScope | None = None) -> dict[str, int | float]:
        timestamp = now or now_utc()
        counts = {status.value: 0 for status in OperationStatus}
        pending: list[datetime] = []
        for operation in self.list(scope=scope, limit=10_000):
            counts[operation.status.value] += 1
            if operation.status in {OperationStatus.QUEUED, OperationStatus.RETRYING, OperationStatus.CLAIMED}:
                pending.append(operation.created_at)
        age = max((timestamp - value).total_seconds() for value in pending) if pending else 0.0
        return {**counts, "oldest_pending_age_seconds": max(age, 0.0)}

    def _by_idempotency(self, operation_type: OperationType, scope: OperationScope, key: str) -> OperationRecord | None:
        row = self._execute(
            """
            SELECT operation_json FROM knowledge_operations
            WHERE operation_type = %s AND scope_key = %s AND idempotency_key = %s
            """,
            (operation_type.value, scope.key, key),
        ).fetchone()
        return OperationRecord.model_validate_json(_value(row, "operation_json", 0)) if row is not None else None

    def _claimed_by(self, operation_id: str, worker_id: str) -> OperationRecord:
        operation = self.get(operation_id)
        if operation.status is not OperationStatus.CLAIMED or operation.lease_owner != worker_id:
            raise OperationConflictError("operation is not claimed by this worker")
        return operation

    def _replace(self, current: OperationRecord, updated: OperationRecord) -> None:
        result = self._execute(
            """
            UPDATE knowledge_operations
            SET status = %s, phase = %s, state_version = %s, attempt_count = %s, next_eligible_retry_at = %s,
                lease_owner = %s, lease_expires_at = %s, updated_at = %s, operation_json = %s
            WHERE operation_id = %s AND state_version = %s
            """,
            (
                updated.status.value,
                updated.phase.value,
                updated.state_version,
                updated.attempt_count,
                _iso(updated.next_eligible_retry_at),
                updated.lease_owner,
                _iso(updated.lease_expires_at),
                updated.updated_at.isoformat(),
                updated.model_dump_json(),
                current.id,
                current.state_version,
            ),
        )
        if result.rowcount != 1:
            raise OperationConflictError("operation changed before this update")

    def _write_transition(
        self,
        current: OperationRecord,
        updated: OperationRecord,
        *,
        event: str,
        actor_id: str,
        detail: str | None = None,
    ) -> None:
        with self._transaction():
            self._replace(current, updated)
            self._append_history(
                OperationHistoryEntry(
                    operation_id=updated.id,
                    state_version=updated.state_version,
                    event=event,
                    status=updated.status,
                    phase=updated.phase,
                    occurred_at=updated.updated_at,
                    actor_id=actor_id,
                    detail=detail,
                )
            )

    def _append_history(self, entry: OperationHistoryEntry) -> None:
        self._execute(
            """
            INSERT INTO knowledge_operation_history
            (operation_id, state_version, event, status, phase, occurred_at, actor_id, detail, history_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                entry.operation_id,
                entry.state_version,
                entry.event,
                entry.status.value,
                entry.phase.value,
                entry.occurred_at.isoformat(),
                entry.actor_id,
                entry.detail,
                entry.model_dump_json(),
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


def _operation_values(operation: OperationRecord) -> tuple[Any, ...]:
    return (
        operation.id,
        operation.operation_type.value,
        operation.scope.key,
        operation.scope.tenant_id,
        operation.scope.matter_id,
        operation.scope.client_id,
        operation.idempotency_key,
        operation.status.value,
        operation.phase.value,
        operation.state_version,
        operation.attempt_count,
        _iso(operation.next_eligible_retry_at),
        operation.lease_owner,
        _iso(operation.lease_expires_at),
        operation.created_at.isoformat(),
        operation.updated_at.isoformat(),
        operation.model_dump_json(),
    )


def _immutable_fingerprint(operation: OperationRecord) -> str:
    value = operation.model_dump(mode="json")
    for field in (
        "id", "status", "phase", "attempt_count", "state_version", "created_at", "updated_at",
        "last_successful_checkpoint", "failure_category", "diagnostic", "next_eligible_retry_at",
        "lease_owner", "lease_expires_at", "result_entity_id", "result_edge_id", "audit_entry_hashes",
    ):
        value.pop(field, None)
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _append_distinct(existing: list[str], value: str | None) -> list[str]:
    return existing if value is None or value in existing else [*existing, value]


def _safe_diagnostic(value: str) -> str:
    return " ".join(value.replace("\n", " ").split())[:500]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _value(row: Any, key: str, index: int) -> str:
    return str(row[key]) if isinstance(row, dict) else str(row[index])


__all__ = ["PostgresOperationStore"]
