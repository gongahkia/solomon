from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from stonks_cli.vnext.database import SQLiteConnectionFactory
from stonks_cli.vnext.errors import VNextInvariantError
from stonks_cli.vnext.foundation import Clock, as_utc

_MIGRATION_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*\Z")
MigrationFunction = Callable[[sqlite3.Connection], None]
_MIGRATIONS_TABLE = "vnext_schema_migrations"


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: MigrationFunction

    def __post_init__(self) -> None:
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ValueError("migration version must be a positive integer")
        if not isinstance(self.name, str) or not _MIGRATION_NAME_PATTERN.fullmatch(self.name):
            raise ValueError("invalid migration name")
        if not callable(self.apply):
            raise TypeError("migration apply must be callable")


@dataclass(frozen=True)
class MigrationRegistry:
    migrations: tuple[Migration, ...]

    def __post_init__(self) -> None:
        if not self.migrations:
            raise ValueError("migration registry must not be empty")
        versions = tuple(migration.version for migration in self.migrations)
        expected = tuple(range(1, len(self.migrations) + 1))
        if versions != expected:
            raise ValueError("migration versions must be contiguous and ordered from 1")
        if len({migration.name for migration in self.migrations}) != len(self.migrations):
            raise ValueError("migration names must be unique")

    @property
    def latest_version(self) -> int:
        return self.migrations[-1].version

    def pending_after(self, applied_version: int) -> tuple[Migration, ...]:
        if not isinstance(applied_version, int) or isinstance(applied_version, bool):
            raise ValueError("applied migration version must be an integer")
        if applied_version < 0 or applied_version > self.latest_version:
            raise ValueError("applied migration version is outside registry range")
        return tuple(migration for migration in self.migrations if migration.version > applied_version)


@dataclass(frozen=True)
class MigrationRunner:
    factory: SQLiteConnectionFactory
    registry: MigrationRegistry
    clock: Clock

    def run(self) -> tuple[Migration, ...]:
        connection = self.factory.connect()
        try:
            _ensure_migrations_table(connection)
            applied_count = _validated_applied_count(connection, self.registry)
            pending = self.registry.pending_after(applied_count)
            with connection:
                for migration in pending:
                    migration.apply(connection)
                    applied_at = self.clock.now().isoformat().replace("+00:00", "Z")
                    connection.execute(
                        f"INSERT INTO {_MIGRATIONS_TABLE}(version, name, applied_at) VALUES (?, ?, ?)",
                        (migration.version, migration.name, applied_at),
                    )
            return pending
        finally:
            connection.close()


def _ensure_migrations_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_MIGRATIONS_TABLE} (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
        )
        """
    )
    connection.commit()


def _validated_applied_count(connection: sqlite3.Connection, registry: MigrationRegistry) -> int:
    rows = connection.execute(f"SELECT version, name, applied_at FROM {_MIGRATIONS_TABLE} ORDER BY version").fetchall()
    for expected_version, row in enumerate(rows, start=1):
        version = row["version"]
        name = row["name"]
        applied_at = row["applied_at"]
        if not isinstance(version, int) or isinstance(version, bool) or version != expected_version:
            raise VNextInvariantError("malformed migration history")
        if version > registry.latest_version or name != registry.migrations[version - 1].name:
            raise VNextInvariantError("migration history does not match registry")
        if not isinstance(applied_at, str):
            raise VNextInvariantError("malformed migration timestamp")
        try:
            as_utc(datetime.fromisoformat(applied_at))
        except ValueError as error:
            raise VNextInvariantError("malformed migration timestamp") from error
    return len(rows)
