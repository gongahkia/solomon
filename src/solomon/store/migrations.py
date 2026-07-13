# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal

from solomon.currency.models import now_utc

MigrationBackend = Literal["sqlite", "postgres"]
PostgresExecute = Callable[[str, tuple[Any, ...]], Any]


class MigrationStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class SchemaMigration:
    scope: str
    version: int
    name: str
    sqlite_statements: tuple[str, ...]
    postgres_statements: tuple[str, ...]

    def statements_for(self, backend: MigrationBackend) -> tuple[str, ...]:
        return self.sqlite_statements if backend == "sqlite" else self.postgres_statements

    def fingerprint_for(self, backend: MigrationBackend) -> str:
        statements = "\n".join(self.statements_for(backend))
        encoded = f"{self.scope}\n{self.version}\n{self.name}\n{statements}".encode()
        return sha256(encoded).hexdigest()


def apply_sqlite_migrations(connection: Any, migrations: Sequence[SchemaMigration]) -> list[SchemaMigration]:
    ordered = _validate_migrations(migrations)
    with connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                scope TEXT NOT NULL,
                version INTEGER NOT NULL,
                name TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                applied_at TEXT NOT NULL,
                PRIMARY KEY(scope, version)
            )
            """
        )
        state = _sqlite_state(connection, ordered[0].scope if ordered else None)
        pending = _pending_migrations(ordered, state, "sqlite")
        for migration in pending:
            for statement in migration.sqlite_statements:
                connection.execute(statement)
            connection.execute(
                """
                INSERT INTO schema_migrations (scope, version, name, fingerprint, applied_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    migration.scope,
                    migration.version,
                    migration.name,
                    migration.fingerprint_for("sqlite"),
                    now_utc().isoformat(),
                ),
            )
    return pending


def apply_postgres_migrations(execute: PostgresExecute, migrations: Sequence[SchemaMigration]) -> list[SchemaMigration]:
    ordered = _validate_migrations(migrations)
    execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            scope TEXT NOT NULL,
            version BIGINT NOT NULL,
            name TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            PRIMARY KEY(scope, version)
        )
        """,
        (),
    )
    state = _postgres_state(execute, ordered[0].scope if ordered else None)
    pending = _pending_migrations(ordered, state, "postgres")
    for migration in pending:
        for statement in migration.postgres_statements:
            execute(statement, ())
        execute(
            """
            INSERT INTO schema_migrations (scope, version, name, fingerprint, applied_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                migration.scope,
                migration.version,
                migration.name,
                migration.fingerprint_for("postgres"),
                now_utc().isoformat(),
            ),
        )
    return pending


def sqlite_knowledge_store_migrations() -> tuple[SchemaMigration, ...]:
    return (
        SchemaMigration(
            scope="knowledge-store",
            version=1,
            name="knowledge-events-and-current-state",
            sqlite_statements=(
                """
                CREATE TABLE IF NOT EXISTS knowledge_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """,
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
                """,
                "CREATE INDEX IF NOT EXISTS idx_knowledge_items_state ON knowledge_items(currency_state)",
                "CREATE INDEX IF NOT EXISTS idx_knowledge_items_scope ON knowledge_items(matter_id, client_id)",
                "CREATE INDEX IF NOT EXISTS idx_knowledge_events_time ON knowledge_events(occurred_at, seq)",
            ),
            postgres_statements=(),
        ),
        SchemaMigration(
            scope="knowledge-store",
            version=2,
            name="transactional-outbox",
            sqlite_statements=(
                """
                CREATE TABLE IF NOT EXISTS outbox_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    delivered_at TEXT,
                    delivery_attempts INTEGER NOT NULL,
                    last_error TEXT,
                    event_json TEXT NOT NULL
                )
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_outbox_events_pending
                ON outbox_events(delivered_at, available_at, event_id)
                """,
            ),
            postgres_statements=(),
        ),
    )


def _validate_migrations(migrations: Sequence[SchemaMigration]) -> tuple[SchemaMigration, ...]:
    ordered = tuple(migrations)
    if not ordered:
        return ordered
    scope = ordered[0].scope
    versions: set[int] = set()
    previous_version = 0
    for migration in ordered:
        if not migration.scope:
            raise MigrationStateError("migration scope is required")
        if migration.scope != scope:
            raise MigrationStateError("a migration batch must have one scope")
        if migration.version < 1:
            raise MigrationStateError("migration versions must be positive")
        if migration.version in versions:
            raise MigrationStateError(f"duplicate migration version: {migration.version}")
        if migration.version <= previous_version:
            raise MigrationStateError("migrations must be supplied in ascending version order")
        versions.add(migration.version)
        previous_version = migration.version
    return ordered


def _pending_migrations(
    migrations: Sequence[SchemaMigration],
    state: dict[int, tuple[str, str]],
    backend: MigrationBackend,
) -> list[SchemaMigration]:
    expected_versions = {migration.version for migration in migrations}
    unknown_versions = sorted(set(state).difference(expected_versions))
    if unknown_versions:
        raise MigrationStateError(f"database has unknown applied migrations: {unknown_versions}")
    pending: list[SchemaMigration] = []
    for migration in migrations:
        applied = state.get(migration.version)
        fingerprint = migration.fingerprint_for(backend)
        if applied is None:
            pending.append(migration)
        elif applied != (migration.name, fingerprint):
            raise MigrationStateError(f"migration state does not match {migration.scope}:{migration.version}")
    return pending


def _sqlite_state(connection: Any, scope: str | None) -> dict[int, tuple[str, str]]:
    if scope is None:
        return {}
    rows = connection.execute(
        "SELECT version, name, fingerprint FROM schema_migrations WHERE scope = ? ORDER BY version",
        (scope,),
    ).fetchall()
    return {int(row[0]): (str(row[1]), str(row[2])) for row in rows}


def _postgres_state(execute: PostgresExecute, scope: str | None) -> dict[int, tuple[str, str]]:
    if scope is None:
        return {}
    rows = execute(
        "SELECT version, name, fingerprint FROM schema_migrations WHERE scope = %s ORDER BY version",
        (scope,),
    ).fetchall()
    return {int(row[0]): (str(row[1]), str(row[2])) for row in rows}


__all__ = [
    "MigrationBackend",
    "MigrationStateError",
    "PostgresExecute",
    "SchemaMigration",
    "apply_postgres_migrations",
    "apply_sqlite_migrations",
    "sqlite_knowledge_store_migrations",
]
