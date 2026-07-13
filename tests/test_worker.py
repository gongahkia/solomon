# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pytest

from solomon.api.service import SolomonService
from solomon.api.service_models import DocumentSourceRequest
from solomon.sources.models import DocumentSourceKind
from solomon.worker import sync_enabled_filesystem_sources


def test_worker_syncs_enabled_filesystem_sources_and_skips_unsupported(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "memo.txt").write_text("worker source document", encoding="utf-8")
    service.register_document_source(
        DocumentSourceRequest(name="filesystem", kind=DocumentSourceKind.FILESYSTEM, root_ref=str(source_root))
    )
    service.register_document_source(
        DocumentSourceRequest(
            name="api",
            kind=DocumentSourceKind.API,
            root_ref="https://connector.example.test/documents",
        )
    )

    batch = sync_enabled_filesystem_sources(service)

    assert batch.attempted == 1
    assert batch.succeeded == 1
    assert batch.failed == 0
    assert batch.skipped == 1


def test_worker_rejects_invalid_limit(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")

    with pytest.raises(ValueError, match="limit must be at least one"):
        sync_enabled_filesystem_sources(service, limit=0)
