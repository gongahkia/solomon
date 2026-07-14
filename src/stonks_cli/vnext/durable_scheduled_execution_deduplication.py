from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from stonks_cli.vnext.database import SQLiteConnectionFactory
from stonks_cli.vnext.foundation import as_utc

_JOB_ID_PATTERN = re.compile(r"[a-z][a-z0-9._-]*\Z")
_CLAIMS_TABLE = "vnext_scheduled_execution_claims"


@dataclass(frozen=True)
class ScheduledExecutionSlot:
    job_id: str
    scheduled_for: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.job_id, str) or not _JOB_ID_PATTERN.fullmatch(self.job_id):
            raise ValueError("scheduled execution job ID is invalid")
        object.__setattr__(self, "scheduled_for", as_utc(self.scheduled_for))


@dataclass(frozen=True)
class DurableScheduledExecutionDeduplicator:
    factory: SQLiteConnectionFactory

    def __post_init__(self) -> None:
        if not isinstance(self.factory, SQLiteConnectionFactory):
            raise TypeError("durable scheduled-execution deduplicator requires a SQLite factory")

    def initialize(self) -> None:
        with self.factory.connect() as connection:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_CLAIMS_TABLE} (
                    job_id TEXT NOT NULL,
                    scheduled_for TEXT NOT NULL,
                    PRIMARY KEY(job_id, scheduled_for)
                )
                """
            )

    def claim(self, slot: ScheduledExecutionSlot) -> bool:
        if not isinstance(slot, ScheduledExecutionSlot):
            raise TypeError("scheduled execution slot is invalid")
        self.initialize()
        with self.factory.connect() as connection:
            cursor = connection.execute(
                f"INSERT INTO {_CLAIMS_TABLE}(job_id, scheduled_for) VALUES (?, ?) ON CONFLICT(job_id, scheduled_for) DO NOTHING",
                (slot.job_id, slot.scheduled_for.isoformat().replace("+00:00", "Z")),
            )
        return cursor.rowcount == 1
