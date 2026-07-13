# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sqlite3
from pathlib import Path

from solomon.contracts import SyncCheckpoint
from solomon.currency.models import now_utc
from solomon.sources.models import (
    CandidateClaim,
    CandidateClaimStatus,
    DocumentExtractionState,
    DocumentSource,
    SourceChangeEvent,
    SourceChangeKind,
    SourceDocument,
    SourceSyncRun,
)


class SourceNotFoundError(KeyError):
    """Raised when a document source is missing."""


class SourceDocumentNotFoundError(KeyError):
    """Raised when a source document version is missing."""


class CandidateClaimNotFoundError(KeyError):
    """Raised when a candidate claim is missing."""


class SQLiteDocumentStore:
    """Append-oriented source-document and candidate-claim store for local deployments."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self.initialize()

    def close(self) -> None:
        self._conn.close()

    def initialize(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS document_sources (
                    source_id TEXT PRIMARY KEY,
                    source_json TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_documents (
                    document_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    previous_version_id TEXT,
                    content_sha256 TEXT NOT NULL,
                    extraction_state TEXT NOT NULL,
                    deleted_at TEXT,
                    ingested_at TEXT NOT NULL,
                    document_json TEXT NOT NULL,
                    UNIQUE(source_id, external_id, version)
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_source_documents_external "
                "ON source_documents(source_id, external_id, version DESC)"
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS candidate_claims (
                    candidate_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    candidate_json TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_candidate_claims_document "
                "ON candidate_claims(document_id, status, created_at)"
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_sync_cursors (
                    source_id TEXT PRIMARY KEY,
                    checkpoint_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_change_events (
                    event_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    event_json TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_source_change_events "
                "ON source_change_events(source_id, external_id, occurred_at, event_id)"
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_sync_runs (
                    run_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    run_json TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_source_sync_runs "
                "ON source_sync_runs(source_id, started_at DESC, run_id DESC)"
            )

    def upsert_source(self, source: DocumentSource) -> DocumentSource:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO document_sources (source_id, source_json, kind, enabled, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    source_json = excluded.source_json,
                    kind = excluded.kind,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    source.id,
                    source.model_dump_json(),
                    source.kind.value,
                    int(source.enabled),
                    source.updated_at.isoformat(),
                ),
            )
        return source

    def get_source(self, source_id: str) -> DocumentSource:
        row = self._conn.execute(
            "SELECT source_json FROM document_sources WHERE source_id = ?", (source_id,)
        ).fetchone()
        if row is None:
            raise SourceNotFoundError(source_id)
        return DocumentSource.model_validate_json(str(row["source_json"]))

    def list_sources(self) -> list[DocumentSource]:
        rows = self._conn.execute("SELECT source_json FROM document_sources ORDER BY source_id").fetchall()
        return [DocumentSource.model_validate_json(str(row["source_json"])) for row in rows]

    def write_document(self, document: SourceDocument) -> SourceDocument:
        self.get_source(document.source_id)
        latest = self._latest_document(document.source_id, document.external_id)
        if (
            latest is not None
            and latest.content_sha256 == document.content_sha256
            and latest.deleted_at == document.deleted_at
            and latest.filename == document.filename
            and latest.mime_type == document.mime_type
            and latest.extraction_state == document.extraction_state
            and latest.extraction_reason == document.extraction_reason
            and latest.metadata == document.metadata
        ):
            return latest
        if latest is not None:
            document = document.model_copy(
                update={"version": latest.version + 1, "previous_version_id": latest.id}
            )
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO source_documents
                (document_id, source_id, external_id, version, previous_version_id, content_sha256,
                 extraction_state, deleted_at, ingested_at, document_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.id,
                    document.source_id,
                    document.external_id,
                    document.version,
                    document.previous_version_id,
                    document.content_sha256,
                    document.extraction_state.value,
                    document.deleted_at.isoformat() if document.deleted_at else None,
                    document.ingested_at.isoformat(),
                    document.model_dump_json(),
                ),
            )
            self._record_change_event(document, previous=latest)
        return document

    def tombstone_document(self, source_id: str, external_id: str) -> SourceDocument:
        latest = self._latest_document(source_id, external_id)
        if latest is None:
            raise SourceDocumentNotFoundError(f"{source_id}:{external_id}")
        return self.write_document(
            SourceDocument(
                source_id=latest.source_id,
                external_id=latest.external_id,
                filename=latest.filename,
                mime_type=latest.mime_type,
                content="",
                extraction_state=DocumentExtractionState.DELETED,
                deleted_at=now_utc(),
                metadata=latest.metadata,
            )
        )

    def get_document(self, document_id: str) -> SourceDocument:
        row = self._conn.execute(
            "SELECT document_json FROM source_documents WHERE document_id = ?", (document_id,)
        ).fetchone()
        if row is None:
            raise SourceDocumentNotFoundError(document_id)
        return SourceDocument.model_validate_json(str(row["document_json"]))

    def list_documents(self, source_id: str) -> list[SourceDocument]:
        rows = self._conn.execute(
            """
            SELECT document_json FROM source_documents
            WHERE source_id = ?
            ORDER BY external_id, version
            """,
            (source_id,),
        ).fetchall()
        return [SourceDocument.model_validate_json(str(row["document_json"])) for row in rows]

    def list_latest_documents(self, source_id: str) -> list[SourceDocument]:
        latest: dict[str, SourceDocument] = {}
        for document in self.list_documents(source_id):
            current = latest.get(document.external_id)
            if current is None or document.version > current.version:
                latest[document.external_id] = document
        return sorted(latest.values(), key=lambda document: (document.filename, document.external_id))

    def document_versions(self, source_id: str, external_id: str) -> list[SourceDocument]:
        rows = self._conn.execute(
            """
            SELECT document_json FROM source_documents
            WHERE source_id = ? AND external_id = ? ORDER BY version
            """,
            (source_id, external_id),
        ).fetchall()
        return [SourceDocument.model_validate_json(str(row["document_json"])) for row in rows]

    def list_change_events(self, source_id: str, *, external_id: str | None = None) -> list[SourceChangeEvent]:
        if external_id is None:
            rows = self._conn.execute(
                """
                SELECT event_json FROM source_change_events
                WHERE source_id = ? ORDER BY occurred_at, event_id
                """,
                (source_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT event_json FROM source_change_events
                WHERE source_id = ? AND external_id = ? ORDER BY occurred_at, event_id
                """,
                (source_id, external_id),
            ).fetchall()
        return [SourceChangeEvent.model_validate_json(str(row["event_json"])) for row in rows]

    def add_candidate(self, candidate: CandidateClaim) -> CandidateClaim:
        self.get_document(candidate.document_id)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO candidate_claims (candidate_id, document_id, status, created_at, candidate_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    candidate.id,
                    candidate.document_id,
                    candidate.status.value,
                    candidate.created_at.isoformat(),
                    candidate.model_dump_json(),
                ),
            )
        return candidate

    def get_candidate(self, candidate_id: str) -> CandidateClaim:
        row = self._conn.execute(
            "SELECT candidate_json FROM candidate_claims WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise CandidateClaimNotFoundError(candidate_id)
        return CandidateClaim.model_validate_json(str(row["candidate_json"]))

    def list_candidates(
        self,
        document_id: str,
        *,
        status: CandidateClaimStatus | None = None,
    ) -> list[CandidateClaim]:
        if status is None:
            rows = self._conn.execute(
                "SELECT candidate_json FROM candidate_claims WHERE document_id = ? ORDER BY created_at, candidate_id",
                (document_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT candidate_json FROM candidate_claims
                WHERE document_id = ? AND status = ? ORDER BY created_at, candidate_id
                """,
                (document_id, status.value),
            ).fetchall()
        return [CandidateClaim.model_validate_json(str(row["candidate_json"])) for row in rows]

    def update_candidate(self, candidate: CandidateClaim) -> CandidateClaim:
        with self._conn:
            result = self._conn.execute(
                """
                UPDATE candidate_claims SET status = ?, candidate_json = ?
                WHERE candidate_id = ?
                """,
                (candidate.status.value, candidate.model_dump_json(), candidate.id),
            )
        if result.rowcount == 0:
            raise CandidateClaimNotFoundError(candidate.id)
        return candidate

    def get_sync_checkpoint(self, source_id: str) -> SyncCheckpoint | None:
        self.get_source(source_id)
        row = self._conn.execute(
            "SELECT checkpoint_json FROM source_sync_cursors WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        return SyncCheckpoint.model_validate_json(str(row["checkpoint_json"])) if row is not None else None

    def set_sync_checkpoint(self, checkpoint: SyncCheckpoint) -> SyncCheckpoint:
        self.get_source(checkpoint.source_id)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO source_sync_cursors (source_id, checkpoint_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    checkpoint_json = excluded.checkpoint_json,
                    updated_at = excluded.updated_at
                """,
                (checkpoint.source_id, checkpoint.model_dump_json(), now_utc().isoformat()),
            )
        return checkpoint

    def write_sync_run(self, run: SourceSyncRun) -> SourceSyncRun:
        self.get_source(run.source_id)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO source_sync_runs (run_id, source_id, state, started_at, run_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    state = excluded.state,
                    started_at = excluded.started_at,
                    run_json = excluded.run_json
                """,
                (run.id, run.source_id, run.state.value, run.started_at.isoformat(), run.model_dump_json()),
            )
        return run

    def list_sync_runs(self, source_id: str, *, limit: int = 20) -> list[SourceSyncRun]:
        self.get_source(source_id)
        rows = self._conn.execute(
            """
            SELECT run_json FROM source_sync_runs
            WHERE source_id = ? ORDER BY started_at DESC, run_id DESC LIMIT ?
            """,
            (source_id, limit),
        ).fetchall()
        return [SourceSyncRun.model_validate_json(str(row["run_json"])) for row in rows]

    def _latest_document(self, source_id: str, external_id: str) -> SourceDocument | None:
        row = self._conn.execute(
            """
            SELECT document_json FROM source_documents
            WHERE source_id = ? AND external_id = ? ORDER BY version DESC LIMIT 1
            """,
            (source_id, external_id),
        ).fetchone()
        return SourceDocument.model_validate_json(str(row["document_json"])) if row is not None else None

    def _record_change_event(self, document: SourceDocument, *, previous: SourceDocument | None) -> None:
        if document.extraction_state is DocumentExtractionState.DELETED:
            kind = SourceChangeKind.DELETED
        elif previous is None or previous.extraction_state is DocumentExtractionState.DELETED:
            kind = SourceChangeKind.CREATED
        elif previous.filename != document.filename:
            kind = SourceChangeKind.RENAMED
        else:
            kind = SourceChangeKind.MODIFIED
        event = SourceChangeEvent(
            source_id=document.source_id,
            document_id=document.id,
            external_id=document.external_id,
            kind=kind,
            previous_document_id=previous.id if previous is not None else None,
            occurred_at=document.ingested_at,
            metadata={"filename": document.filename, "content_sha256": document.content_sha256},
        )
        self._conn.execute(
            """
            INSERT INTO source_change_events
            (event_id, source_id, external_id, document_id, occurred_at, event_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.source_id,
                event.external_id,
                event.document_id,
                event.occurred_at.isoformat(),
                event.model_dump_json(),
            ),
        )
