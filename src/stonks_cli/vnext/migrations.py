from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

_MIGRATION_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*\Z")
MigrationFunction = Callable[[sqlite3.Connection], None]


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
