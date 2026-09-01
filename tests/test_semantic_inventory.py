# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sqlite3
from pathlib import Path

from solomon.api.service import IngestRequest, SolomonService
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.semantic_inventory import (
    _json_column,
    _json_value,
    _metadata_records,
    _source_records,
    _sqlite_state_records,
    semantic_inventory,
)


def test_semantic_inventory_is_deterministic_and_content_redacting(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="confidential recovery inventory source text",
            source_kind=SourceKind.PARTNER,
            source_ref="inventory-source",
        )
    )

    first = semantic_inventory(service)
    second = semantic_inventory(service)

    assert first == second
    assert first["components"]["knowledge_items"]["count"] == 1
    assert "confidential" not in str(first)


def test_semantic_inventory_helpers_handle_missing_and_unsafe_local_records(tmp_path: Path) -> None:
    assert _source_records(tmp_path / "missing.sqlite3") == {
        "documents": [],
        "changes": [],
        "candidates": [],
        "sources": [],
    }

    database_path = tmp_path / "empty.sqlite3"
    with sqlite3.connect(database_path) as database:
        assert _json_column(database, "missing", "payload") == []

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    target = tmp_path / "target.sqlite3"
    target.write_bytes(b"not-a-database")
    (data_dir / "linked.sqlite3").symlink_to(target)
    assert _sqlite_state_records(data_dir) == [{"path": "linked.sqlite3", "state": "unsafe"}]

    (data_dir / ".solomon-maintenance.json").write_text("not-json", encoding="utf-8")
    (data_dir / "deployment.json").write_text('{"schema": "test"}', encoding="utf-8")
    (data_dir / "linked.json").symlink_to(data_dir / "deployment.json")
    assert _metadata_records(data_dir) == [{"path": "deployment.json", "content": {"schema": "test"}}]
    assert _json_value(b"binary") == {
        "bytes": 6,
        "bytes_sha256": "9a3a45d01531a20e89ac6ae10b0b0beb0492acd7216a368aa062d1a5fecaf9cd",
    }
