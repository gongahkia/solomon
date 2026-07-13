# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pytest

from solomon.connectors import ConnectorConfiguration
from solomon.sources.filesystem import FilesystemDocumentSourceAdapter
from solomon.sources.models import DocumentSource, DocumentSourceKind


def _source(root: Path, **settings: object) -> DocumentSource:
    return DocumentSource(
        id="filesystem-1",
        name="knowledge",
        kind=DocumentSourceKind.FILESYSTEM,
        root_ref=str(root),
        config=ConnectorConfiguration(settings=settings),
    )


def test_filesystem_discovery_recurses_applies_rules_and_returns_deterministic_checkpoint(tmp_path):
    root = tmp_path / "knowledge"
    (root / "public").mkdir(parents=True)
    (root / "private").mkdir()
    (root / "public" / "memo.txt").write_text("current position", encoding="utf-8")
    (root / "public" / "diagram.pdf").write_bytes(b"%PDF")
    (root / "private" / "memo.txt").write_text("restricted", encoding="utf-8")
    adapter = FilesystemDocumentSourceAdapter()
    source = _source(root, include=["**/*.txt"], exclude=["private/**"])

    documents, checkpoint = adapter.discover(source, None)
    repeated, repeated_checkpoint = adapter.discover(source, checkpoint)

    assert adapter.health(source).healthy is True
    assert [document.metadata["relative_path"] for document in documents] == ["public/memo.txt"]
    assert documents[0].content_ref == (root / "public" / "memo.txt").resolve().as_uri()
    assert checkpoint is not None
    assert repeated_checkpoint is not None
    assert checkpoint.cursor == repeated_checkpoint.cursor
    assert documents == repeated


def test_filesystem_discovery_stable_identity_survives_rename_and_rejects_invalid_configuration(tmp_path):
    root = tmp_path / "knowledge"
    root.mkdir()
    original = root / "memo.txt"
    original.write_text("current position", encoding="utf-8")
    adapter = FilesystemDocumentSourceAdapter()
    source = _source(root)

    before, _ = adapter.discover(source, None)
    original.rename(root / "renamed.txt")
    after, _ = adapter.discover(source, None)

    assert before[0].external_id == after[0].external_id
    assert before[0].filename == "memo.txt"
    assert after[0].filename == "renamed.txt"
    with pytest.raises(ValueError, match="include"):
        adapter.discover(_source(root, include="*.txt"), None)
    with pytest.raises(ValueError, match="readable directory"):
        adapter.discover(_source(tmp_path / "missing"), None)
