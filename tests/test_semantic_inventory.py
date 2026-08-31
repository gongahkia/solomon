# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from solomon.api.service import IngestRequest, SolomonService
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.semantic_inventory import semantic_inventory


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
