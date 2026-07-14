from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from stonks_cli.vnext.database import SQLiteConnectionFactory
from stonks_cli.vnext.foundation import as_utc

_LEASE_NAME_PATTERN = re.compile(r"[a-z][a-z0-9._-]*\Z")
_LEASES_TABLE = "vnext_single_run_leases"


@dataclass(frozen=True)
class SingleRunLease:
    name: str
    owner_id: UUID
    acquired_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _LEASE_NAME_PATTERN.fullmatch(self.name):
            raise ValueError("single-run lease name is invalid")
        if not isinstance(self.owner_id, UUID):
            raise TypeError("single-run lease owner ID must be a UUID")
        acquired_at = as_utc(self.acquired_at)
        expires_at = as_utc(self.expires_at)
        if expires_at <= acquired_at:
            raise ValueError("single-run lease expiry is invalid")
        object.__setattr__(self, "acquired_at", acquired_at)
        object.__setattr__(self, "expires_at", expires_at)


@dataclass(frozen=True)
class SingleRunLeaseStore:
    factory: SQLiteConnectionFactory

    def __post_init__(self) -> None:
        if not isinstance(self.factory, SQLiteConnectionFactory):
            raise TypeError("single-run lease store requires a SQLite factory")

    def initialize(self) -> None:
        with self.factory.connect() as connection:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_LEASES_TABLE} (
                    name TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )

    def try_acquire(self, name: str, owner_id: UUID, now: datetime, duration: timedelta) -> SingleRunLease | None:
        acquired_at, expires_at = _lease_window(name, owner_id, now, duration)
        self.initialize()
        with self.factory.connect() as connection:
            cursor = connection.execute(
                f"""
                INSERT INTO {_LEASES_TABLE}(name, owner_id, acquired_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    owner_id = excluded.owner_id,
                    acquired_at = excluded.acquired_at,
                    expires_at = excluded.expires_at
                WHERE {_LEASES_TABLE}.expires_at <= excluded.acquired_at
                """,
                (name, str(owner_id), _format_timestamp(acquired_at), _format_timestamp(expires_at)),
            )
        if cursor.rowcount != 1:
            return None
        return SingleRunLease(name, owner_id, acquired_at, expires_at)

    def renew(self, lease: SingleRunLease, now: datetime, duration: timedelta) -> SingleRunLease | None:
        if not isinstance(lease, SingleRunLease):
            raise TypeError("single-run lease is required")
        current = as_utc(now)
        if current < lease.acquired_at:
            raise ValueError("single-run lease renewal timestamp is invalid")
        _validate_duration(duration)
        expires_at = max(lease.expires_at, current) + duration
        self.initialize()
        with self.factory.connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE {_LEASES_TABLE}
                SET expires_at = ?
                WHERE name = ? AND owner_id = ? AND acquired_at = ? AND expires_at = ? AND expires_at > ?
                """,
                (
                    _format_timestamp(expires_at),
                    lease.name,
                    str(lease.owner_id),
                    _format_timestamp(lease.acquired_at),
                    _format_timestamp(lease.expires_at),
                    _format_timestamp(current),
                ),
            )
        return SingleRunLease(lease.name, lease.owner_id, lease.acquired_at, expires_at) if cursor.rowcount == 1 else None

    def release(self, lease: SingleRunLease) -> bool:
        if not isinstance(lease, SingleRunLease):
            raise TypeError("single-run lease is required")
        self.initialize()
        with self.factory.connect() as connection:
            cursor = connection.execute(
                f"""
                DELETE FROM {_LEASES_TABLE}
                WHERE name = ? AND owner_id = ? AND acquired_at = ? AND expires_at = ?
                """,
                (lease.name, str(lease.owner_id), _format_timestamp(lease.acquired_at), _format_timestamp(lease.expires_at)),
            )
        return cursor.rowcount == 1


def _lease_window(name: str, owner_id: UUID, now: datetime, duration: timedelta) -> tuple[datetime, datetime]:
    if not isinstance(name, str) or not _LEASE_NAME_PATTERN.fullmatch(name):
        raise ValueError("single-run lease name is invalid")
    if not isinstance(owner_id, UUID):
        raise TypeError("single-run lease owner ID must be a UUID")
    _validate_duration(duration)
    acquired_at = as_utc(now)
    return acquired_at, acquired_at + duration


def _validate_duration(duration: timedelta) -> None:
    if not isinstance(duration, timedelta) or duration <= timedelta(0):
        raise ValueError("single-run lease duration is invalid")


def _format_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
