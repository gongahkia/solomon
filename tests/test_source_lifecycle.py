# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from solomon.sources.models import DocumentSource, DocumentSourceKind, SourceChangeKind, SourceDocument
from solomon.sources.store import SQLiteDocumentStore


def test_source_documents_append_versions_tombstones_and_change_events(tmp_path):
    store = SQLiteDocumentStore(tmp_path / "sources.sqlite3")
    source = store.upsert_source(
        DocumentSource(id="source-1", name="files", kind=DocumentSourceKind.FILESYSTEM, root_ref="/knowledge")
    )
    first = store.write_document(
        SourceDocument(
            id="document-1",
            source_id=source.id,
            external_id="filesystem:1:2",
            filename="memo.txt",
            mime_type="text/plain",
            content="first position",
        )
    )
    second = store.write_document(
        SourceDocument(
            id="document-2",
            source_id=source.id,
            external_id=first.external_id,
            filename="memo.txt",
            mime_type="text/plain",
            content="second position",
        )
    )
    renamed = store.write_document(
        SourceDocument(
            id="document-3",
            source_id=source.id,
            external_id=first.external_id,
            filename="renamed.txt",
            mime_type="text/plain",
            content="second position",
        )
    )
    tombstone = store.tombstone_document(source.id, first.external_id)
    versions = store.document_versions(source.id, first.external_id)
    events = store.list_change_events(source.id, external_id=first.external_id)

    assert [document.id for document in versions] == [first.id, second.id, renamed.id, tombstone.id]
    assert [document.previous_version_id for document in versions] == [None, first.id, second.id, renamed.id]
    assert [event.kind for event in events] == [
        SourceChangeKind.CREATED,
        SourceChangeKind.MODIFIED,
        SourceChangeKind.RENAMED,
        SourceChangeKind.DELETED,
    ]
    assert [event.previous_document_id for event in events] == [None, first.id, second.id, renamed.id]
