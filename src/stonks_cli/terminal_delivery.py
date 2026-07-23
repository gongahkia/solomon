from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from stonks_cli.storage import EncryptedLedger


@dataclass(frozen=True)
class TerminalArtifact:
    artifact_id: str
    kind: str
    content: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.artifact_id, self.kind, self.content)
        ):
            raise ValueError("terminal artifact fields are required")
        if self.created_at.tzinfo is None:
            raise ValueError("terminal artifact time must be timezone-aware")
        object.__setattr__(self, "artifact_id", self.artifact_id.strip())
        object.__setattr__(self, "kind", self.kind.strip())
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))


@dataclass(frozen=True)
class ScheduledArtifactStatus:
    profile: str
    job_label: str
    artifact: TerminalArtifact
    status: str

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "failed"}:
            raise ValueError("scheduled artifact status is invalid")


def create_artifact(
    kind: str, content: str, *, created_at: datetime | None = None
) -> TerminalArtifact:
    return TerminalArtifact(uuid4().hex, kind, content, created_at or datetime.now(UTC))


def persist_scheduled_artifact(
    ledger: EncryptedLedger, job_label: str, artifact: TerminalArtifact, status: str
) -> ScheduledArtifactStatus:
    if not isinstance(job_label, str) or not job_label.strip():
        raise ValueError("scheduled artifact job label is required")
    record = ScheduledArtifactStatus(ledger.config.name, job_label.strip(), artifact, status)
    with ledger.connection() as connection:
        _initialize(connection)
        connection.execute(
            "INSERT INTO scheduled_terminal_artifacts VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.profile,
                record.job_label,
                artifact.artifact_id,
                artifact.kind,
                artifact.content,
                artifact.created_at.isoformat(),
                record.status,
            ),
        )
    return record


def latest_scheduled_artifact(
    ledger: EncryptedLedger, job_label: str
) -> ScheduledArtifactStatus | None:
    with ledger.connection() as connection:
        _initialize(connection)
        row = connection.execute(
            "SELECT * FROM scheduled_terminal_artifacts WHERE profile = ? AND job_label = ? ORDER BY created_at DESC, artifact_id DESC LIMIT 1",
            (ledger.config.name, job_label),
        ).fetchone()
    if row is None:
        return None
    return ScheduledArtifactStatus(
        row["profile"],
        row["job_label"],
        TerminalArtifact(
            row["artifact_id"],
            row["kind"],
            row["content"],
            datetime.fromisoformat(row["created_at"]),
        ),
        row["status"],
    )


def render_terminal(artifact: TerminalArtifact) -> str:
    return artifact.content


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduled_terminal_artifacts (
            profile TEXT NOT NULL,
            job_label TEXT NOT NULL,
            artifact_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL
        )
        """
    )
