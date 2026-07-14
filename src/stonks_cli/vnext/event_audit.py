from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

from stonks_cli.vnext.database import SQLiteConnectionFactory
from stonks_cli.vnext.errors import VNextInvariantError
from stonks_cli.vnext.events import StructuredEvent, serialize_structured_event

_AUDIT_ENTRIES_TABLE = "vnext_immutable_event_audit_entries"
_AUDIT_HEAD_TABLE = "vnext_immutable_event_audit_head"


@dataclass(frozen=True)
class ImmutableEventAuditReport:
    entry_count: int
    head_hash: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.entry_count, int) or isinstance(self.entry_count, bool) or self.entry_count < 0:
            raise ValueError("immutable event-audit entry count is invalid")
        if self.entry_count == 0 and self.head_hash is not None:
            raise ValueError("empty immutable event audit must not have a head hash")
        if self.entry_count > 0 and (not isinstance(self.head_hash, str) or len(self.head_hash) != 64):
            raise ValueError("immutable event-audit head hash is invalid")


@dataclass(frozen=True)
class ImmutableEventAudit:
    factory: SQLiteConnectionFactory

    def __post_init__(self) -> None:
        if not isinstance(self.factory, SQLiteConnectionFactory):
            raise TypeError("immutable event audit requires a SQLite factory")

    def append(self, event: StructuredEvent) -> ImmutableEventAuditReport:
        if not isinstance(event, StructuredEvent):
            raise TypeError("immutable event audit requires a structured event")
        serialized_event = serialize_structured_event(event)
        self.initialize()
        try:
            with self.factory.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                head = _load_head(connection)
                previous_hash = head[1] or ""
                record_hash = _record_hash(previous_hash, serialized_event)
                connection.execute(
                    f"INSERT INTO {_AUDIT_ENTRIES_TABLE}(event_id,event_json,previous_hash,record_hash) VALUES (?,?,?,?)",
                    (str(event.event_id), serialized_event, previous_hash or None, record_hash),
                )
                entry_count = head[0] + 1
                connection.execute(
                    f"UPDATE {_AUDIT_HEAD_TABLE} SET entry_count = ?, head_hash = ? WHERE singleton = 1",
                    (entry_count, record_hash),
                )
        except sqlite3.IntegrityError as error:
            raise VNextInvariantError("immutable event audit cannot append duplicate event") from error
        return ImmutableEventAuditReport(entry_count, record_hash)

    def initialize(self) -> None:
        with self.factory.connect() as connection:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_AUDIT_ENTRIES_TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    event_json TEXT NOT NULL,
                    previous_hash TEXT,
                    record_hash TEXT NOT NULL UNIQUE
                )
                """
            )
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_AUDIT_HEAD_TABLE} (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    entry_count INTEGER NOT NULL,
                    head_hash TEXT
                )
                """
            )
            connection.execute(
                f"INSERT OR IGNORE INTO {_AUDIT_HEAD_TABLE}(singleton,entry_count,head_hash) VALUES (1,0,NULL)"
            )

    def verify(self) -> ImmutableEventAuditReport:
        self.initialize()
        with self.factory.connect(read_only=True) as connection:
            rows = connection.execute(
                f"SELECT sequence,event_json,previous_hash,record_hash FROM {_AUDIT_ENTRIES_TABLE} ORDER BY sequence"
            ).fetchall()
            head = _load_head(connection)
        previous_hash = ""
        expected_sequence = 1
        for row in rows:
            if tuple(row.keys()) != ("sequence", "event_json", "previous_hash", "record_hash"):
                raise VNextInvariantError("immutable event audit row is malformed")
            sequence, event_json, stored_previous_hash, stored_record_hash = tuple(row)
            if sequence != expected_sequence or not isinstance(event_json, str) or stored_previous_hash != (previous_hash or None):
                raise VNextInvariantError("immutable event audit chain is broken")
            expected_record_hash = _record_hash(previous_hash, event_json)
            if not isinstance(stored_record_hash, str) or stored_record_hash != expected_record_hash:
                raise VNextInvariantError("immutable event audit chain is broken")
            previous_hash = stored_record_hash
            expected_sequence += 1
        report = ImmutableEventAuditReport(len(rows), previous_hash or None)
        if head != (report.entry_count, report.head_hash):
            raise VNextInvariantError("immutable event audit head is inconsistent")
        return report


def _load_head(connection: sqlite3.Connection) -> tuple[int, str | None]:
    rows = connection.execute(f"SELECT entry_count,head_hash FROM {_AUDIT_HEAD_TABLE} WHERE singleton = 1").fetchall()
    if len(rows) != 1:
        raise VNextInvariantError("immutable event audit head is malformed")
    entry_count, head_hash = tuple(rows[0])
    try:
        report = ImmutableEventAuditReport(entry_count, head_hash)
    except (TypeError, ValueError) as error:
        raise VNextInvariantError("immutable event audit head is malformed") from error
    return report.entry_count, report.head_hash


def _record_hash(previous_hash: str, serialized_event: str) -> str:
    return hashlib.sha256(f"{previous_hash}\n{serialized_event}".encode()).hexdigest()
