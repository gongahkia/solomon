# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

import pytest

from solomon.store.migrations import (
    MigrationStateError,
    SchemaMigration,
    apply_postgres_migrations,
    apply_sqlite_migrations,
)


def _migrations() -> tuple[SchemaMigration, ...]:
    return (
        SchemaMigration(
            scope="test-schema",
            version=1,
            name="create-first-table",
            sqlite_statements=("CREATE TABLE first_table (id INTEGER PRIMARY KEY)",),
            postgres_statements=("CREATE TABLE first_table (id BIGINT PRIMARY KEY)",),
        ),
        SchemaMigration(
            scope="test-schema",
            version=2,
            name="create-second-table",
            sqlite_statements=("CREATE TABLE second_table (id INTEGER PRIMARY KEY)",),
            postgres_statements=("CREATE TABLE second_table (id BIGINT PRIMARY KEY)",),
        ),
    )


def test_sqlite_migrations_apply_in_order_idempotently_and_detect_state_drift():
    connection = sqlite3.connect(":memory:")
    migrations = _migrations()

    assert apply_sqlite_migrations(connection, migrations) == list(migrations)
    assert apply_sqlite_migrations(connection, migrations) == []
    assert connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall() == [(1,), (2,)]
    connection.execute(
        "UPDATE schema_migrations SET fingerprint = ? WHERE scope = ? AND version = ?",
        ("tampered", "test-schema", 1),
    )
    with pytest.raises(MigrationStateError, match="does not match"):
        apply_sqlite_migrations(connection, migrations)


def test_migration_runner_rejects_unordered_or_unknown_database_state():
    connection = sqlite3.connect(":memory:")
    migrations = _migrations()

    with pytest.raises(MigrationStateError, match="ascending"):
        apply_sqlite_migrations(connection, tuple(reversed(migrations)))
    apply_sqlite_migrations(connection, migrations)
    connection.execute(
        "INSERT INTO schema_migrations (scope, version, name, fingerprint, applied_at) VALUES (?, ?, ?, ?, ?)",
        ("test-schema", 99, "unknown", "unknown", "2026-07-13T00:00:00+00:00"),
    )
    with pytest.raises(MigrationStateError, match="unknown"):
        apply_sqlite_migrations(connection, migrations)


def test_sqlite_migrations_roll_back_failed_fresh_batch() -> None:
    connection = sqlite3.connect(":memory:")
    migrations = (
        SchemaMigration(
            scope="test-schema",
            version=1,
            name="failing-migration",
            sqlite_statements=("CREATE TABLE transient_table (id INTEGER PRIMARY KEY)", "not valid SQL"),
            postgres_statements=(),
        ),
    )

    with pytest.raises(sqlite3.OperationalError):
        apply_sqlite_migrations(connection, migrations)

    assert (
        connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('schema_migrations', 'transient_table')"
        ).fetchall()
        == []
    )


@dataclass
class FakeCursor:
    rows: list[tuple[Any, ...]]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class FakePostgres:
    def __init__(self, *, mapping_rows: bool = False) -> None:
        self.state: dict[int, tuple[str, str]] = {}
        self.statements: list[str] = []
        self.mapping_rows = mapping_rows

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> FakeCursor:
        normalized = " ".join(sql.split())
        self.statements.append(normalized)
        if normalized.startswith("SELECT version, name, fingerprint"):
            if self.mapping_rows:
                return FakeCursor(
                    [
                        {"version": version, "name": state[0], "fingerprint": state[1]}
                        for version, state in sorted(self.state.items())
                    ]
                )
            return FakeCursor([(version, *state) for version, state in sorted(self.state.items())])
        if normalized.startswith("INSERT INTO schema_migrations"):
            self.state[int(params[1])] = (str(params[2]), str(params[3]))
        return FakeCursor([])


def test_postgres_migrations_apply_in_order_and_skip_already_applied_versions():
    postgres = FakePostgres()
    migrations = _migrations()

    assert apply_postgres_migrations(postgres.execute, migrations) == list(migrations)
    assert apply_postgres_migrations(postgres.execute, migrations) == []
    assert [version for version in sorted(postgres.state)] == [1, 2]
    assert postgres.statements.count("CREATE TABLE first_table (id BIGINT PRIMARY KEY)") == 1


def test_postgres_migrations_support_dictionary_rows():
    postgres = FakePostgres(mapping_rows=True)
    migrations = _migrations()

    assert apply_postgres_migrations(postgres.execute, migrations) == list(migrations)
    assert apply_postgres_migrations(postgres.execute, migrations) == []
