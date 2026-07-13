# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from solomon.connectors import ConnectorConfiguration
from solomon.sources.models import DocumentExtractionState, DocumentSource, DocumentSourceKind
from solomon.sources.store import SQLiteDocumentStore
from solomon.sources.sync import FilesystemSourceSynchronizer


def test_filesystem_sync_only_writes_changed_documents_persists_cursor_and_tombstones_deletions(tmp_path):
    root = tmp_path / "knowledge"
    root.mkdir()
    memo = root / "memo.txt"
    removed = root / "removed.txt"
    memo.write_text("first position", encoding="utf-8")
    removed.write_text("removed position", encoding="utf-8")
    store = SQLiteDocumentStore(tmp_path / "sources.sqlite3")
    source = store.upsert_source(
        DocumentSource(
            id="filesystem-1",
            name="knowledge",
            kind=DocumentSourceKind.FILESYSTEM,
            root_ref=str(root),
            config=ConnectorConfiguration(settings={"include": ["**/*.txt"]}),
        )
    )
    synchronizer = FilesystemSourceSynchronizer(store)

    first = synchronizer.sync(source.id)
    repeated = synchronizer.sync(source.id)
    memo.write_text("second position", encoding="utf-8")
    removed.unlink()
    changed = synchronizer.sync(source.id)

    assert first.created == 2
    assert repeated.unchanged == 2
    assert changed.updated == 1
    assert changed.deleted == 1
    assert store.get_sync_checkpoint(source.id) == changed.checkpoint
    documents = store.list_documents(source.id)
    assert len(documents) == 4
    assert sorted(document.version for document in documents if document.filename == "memo.txt") == [1, 2]
    assert any(document.extraction_state is DocumentExtractionState.DELETED for document in documents)
