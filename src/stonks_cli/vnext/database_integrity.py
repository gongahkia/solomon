from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from stonks_cli.vnext.database import SQLiteConnectionFactory
from stonks_cli.vnext.errors import VNextInvariantError


@dataclass(frozen=True)
class ForeignKeyViolation:
    table: str
    row_id: int
    parent_table: str
    foreign_key_index: int

    def __post_init__(self) -> None:
        if not isinstance(self.table, str) or not self.table:
            raise ValueError("foreign-key violation table is invalid")
        if not isinstance(self.row_id, int) or isinstance(self.row_id, bool) or self.row_id < 1:
            raise ValueError("foreign-key violation row ID is invalid")
        if not isinstance(self.parent_table, str) or not self.parent_table:
            raise ValueError("foreign-key violation parent table is invalid")
        if not isinstance(self.foreign_key_index, int) or isinstance(self.foreign_key_index, bool) or self.foreign_key_index < 0:
            raise ValueError("foreign-key violation index is invalid")


@dataclass(frozen=True)
class DatabaseIntegrityReport:
    integrity_messages: tuple[str, ...]
    foreign_key_violations: tuple[ForeignKeyViolation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.integrity_messages, tuple) or not self.integrity_messages or not all(
            isinstance(message, str) and message for message in self.integrity_messages
        ):
            raise ValueError("database integrity messages are invalid")
        if not isinstance(self.foreign_key_violations, tuple) or not all(
            isinstance(violation, ForeignKeyViolation) for violation in self.foreign_key_violations
        ):
            raise ValueError("database foreign-key violations are invalid")

    @property
    def healthy(self) -> bool:
        return self.integrity_messages == ("ok",) and not self.foreign_key_violations


def check_database_integrity(factory: SQLiteConnectionFactory) -> DatabaseIntegrityReport:
    if not isinstance(factory, SQLiteConnectionFactory):
        raise TypeError("database integrity check requires a SQLite factory")
    with factory.connect(read_only=True) as connection:
        integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
        foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
    messages = _integrity_messages(integrity_rows)
    violations = tuple(_foreign_key_violation(row) for row in foreign_key_rows)
    return DatabaseIntegrityReport(messages, violations)


def _integrity_messages(rows: list[sqlite3.Row]) -> tuple[str, ...]:
    messages = tuple(row[0] for row in rows)
    if not messages or not all(isinstance(message, str) and message for message in messages):
        raise VNextInvariantError("database integrity check output is malformed")
    return messages


def _foreign_key_violation(row: sqlite3.Row) -> ForeignKeyViolation:
    try:
        table = row["table"]
        row_id = row["rowid"]
        parent_table = row["parent"]
        foreign_key_index = row["fkid"]
        return ForeignKeyViolation(table, row_id, parent_table, foreign_key_index)
    except (IndexError, KeyError, TypeError, ValueError) as error:
        raise VNextInvariantError("database foreign-key check output is malformed") from error
