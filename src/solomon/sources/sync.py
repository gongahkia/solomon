# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import unquote, urlparse

from solomon.api.schemas import SolomonModel
from solomon.contracts import SyncCheckpoint
from solomon.sources.extract import extract_document_bytes
from solomon.sources.filesystem import FilesystemDocumentSourceAdapter
from solomon.sources.models import DocumentExtractionState, SourceDocument
from solomon.sources.store import SQLiteDocumentStore


class FilesystemSyncResult(SolomonModel):
    source_id: str
    discovered: int
    created: int
    updated: int
    unchanged: int
    deleted: int
    checkpoint: SyncCheckpoint


class FilesystemSourceSynchronizer:
    def __init__(self, store: SQLiteDocumentStore, adapter: FilesystemDocumentSourceAdapter | None = None) -> None:
        self.store = store
        self.adapter = adapter or FilesystemDocumentSourceAdapter()

    def sync(self, source_id: str) -> FilesystemSyncResult:
        source = self.store.get_source(source_id)
        if not source.enabled:
            raise ValueError("filesystem source is disabled")
        checkpoint = self.store.get_sync_checkpoint(source_id)
        discovered, next_checkpoint = self.adapter.discover(source, checkpoint)
        if next_checkpoint is None:
            raise RuntimeError("filesystem discovery did not return a checkpoint")
        latest = _latest_documents(self.store.list_documents(source_id))
        discovered_ids: set[str] = set()
        created = 0
        updated = 0
        unchanged = 0
        for document in discovered:
            discovered_ids.add(document.external_id)
            raw = _read_content_ref(document.content_ref)
            source_sha256 = hashlib.sha256(raw).hexdigest()
            previous = latest.get(document.external_id)
            if _is_unchanged(previous, document.filename, source_sha256):
                unchanged += 1
                continue
            extracted = extract_document_bytes(raw, filename=document.filename, mime_type=document.mime_type)
            stored = self.store.write_document(
                SourceDocument(
                    source_id=source.id,
                    external_id=document.external_id,
                    filename=document.filename,
                    mime_type=extracted.mime_type,
                    content=extracted.text,
                    extraction_state=extracted.state,
                    extraction_reason=extracted.reason,
                    metadata={
                        **document.metadata,
                        "content_ref": document.content_ref,
                        "source_sha256": source_sha256,
                        "extraction": extracted.metadata,
                    },
                )
            )
            latest[stored.external_id] = stored
            if previous is None or previous.extraction_state is DocumentExtractionState.DELETED:
                created += 1
            else:
                updated += 1
        deleted = 0
        for external_id, latest_document in latest.items():
            missing_from_discovery = external_id not in discovered_ids
            is_live = latest_document.extraction_state is not DocumentExtractionState.DELETED
            if missing_from_discovery and is_live:
                self.store.tombstone_document(source_id, external_id)
                deleted += 1
        self.store.set_sync_checkpoint(next_checkpoint)
        return FilesystemSyncResult(
            source_id=source_id,
            discovered=len(discovered),
            created=created,
            updated=updated,
            unchanged=unchanged,
            deleted=deleted,
            checkpoint=next_checkpoint,
        )


def _latest_documents(documents: list[SourceDocument]) -> dict[str, SourceDocument]:
    latest: dict[str, SourceDocument] = {}
    for document in documents:
        current = latest.get(document.external_id)
        if current is None or document.version > current.version:
            latest[document.external_id] = document
    return latest


def _is_unchanged(document: SourceDocument | None, filename: str, source_sha256: str) -> bool:
    return (
        document is not None
        and document.extraction_state is not DocumentExtractionState.DELETED
        and document.filename == filename
        and document.metadata.get("source_sha256") == source_sha256
    )


def _read_content_ref(content_ref: str) -> bytes:
    parsed = urlparse(content_ref)
    if parsed.scheme != "file":
        raise ValueError("filesystem discovery returned a non-file content reference")
    return Path(unquote(parsed.path)).read_bytes()


__all__ = ["FilesystemSourceSynchronizer", "FilesystemSyncResult"]
