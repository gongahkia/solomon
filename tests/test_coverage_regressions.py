# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from solomon.api.service import SolomonService
from solomon.boundary.engine.mapping_store import VolatileMappingStore
from solomon.boundary.engine.schemas import MappingEntry
from solomon.currency.feeds import load_authority_changes
from solomon.currency.models import KnowledgeItem, KnowledgeKind, Provenance, SourceKind
from solomon.currency.supersession import propose_supersession
from solomon.graph.models import DependencyEdge, EdgeType
from solomon.mcp.tools.runtime import SolomonMCPRuntime


def _item(item_id: str, *, year: int, metadata: dict[str, str]) -> KnowledgeItem:
    timestamp = datetime(year, 1, 1, tzinfo=timezone.utc)
    return KnowledgeItem(
        id=item_id,
        kind=KnowledgeKind.POSITION,
        content=f"position {item_id}",
        provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref=item_id),
        valid_from=timestamp,
        ingested_at=timestamp,
        metadata=metadata,
    )


def test_volatile_mapping_store_returns_copies_and_clears_on_pop() -> None:
    store = VolatileMappingStore()
    mapping = [MappingEntry(placeholder="[CLIENT_1]", original_text="Client A")]

    store.put("context-1", mapping)
    mapping.clear()
    stored = store.get("context-1")

    assert stored is not None
    assert stored[0].original_text == "Client A"
    stored.clear()
    assert store.count() == 1
    assert store.pop("context-1") is not None
    assert store.get("context-1") is None
    assert store.pop("missing") is None
    assert store.count() == 0


def test_invalid_authority_feed_suffix_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="authority feed"):
        load_authority_changes(tmp_path / "changes.txt")


def test_supersession_proposal_rejects_incomplete_or_non_predecessor_candidates() -> None:
    incomplete = _item("incomplete", year=2025, metadata={})
    old = _item("old", year=2023, metadata={"topic": "x", "jurisdiction": "SG"})
    new = _item("new", year=2025, metadata={"topic": "x", "jurisdiction": "SG"})
    later = _item("later", year=2026, metadata={"topic": "x", "jurisdiction": "SG"})

    assert propose_supersession(incomplete, [old]) == []
    assert propose_supersession(new, [new, later]) == []


def test_dependency_edge_rejects_invalid_target_shapes() -> None:
    with pytest.raises(ValueError, match="external dependency"):
        DependencyEdge(
            source_id="item-a",
            target_id="item-b",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="knowledge_item",
        )
    with pytest.raises(ValueError, match="internal dependency"):
        DependencyEdge(
            source_id="item-a",
            target_id="authority-a",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_INTERNAL,
            target_kind="external_authority",
        )


def test_mcp_currency_report_validates_input_and_renders_pdf(tmp_path: Path) -> None:
    runtime = SolomonMCPRuntime(SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal"))
    period_start = "2026-01-01T00:00:00+00:00"
    period_end = "2026-12-31T00:00:00+00:00"

    invalid_scope = runtime.currency_report(period_start=period_start, period_end=period_end, scope="team")
    invalid_format = runtime.currency_report(period_start=period_start, period_end=period_end, format="csv")
    pdf = runtime.currency_report(period_start=period_start, period_end=period_end, format="pdf")

    assert invalid_scope["error"]["code"] == "bad_request"
    assert invalid_format["error"]["code"] == "bad_request"
    assert pdf["format"] == "pdf"
    assert pdf["pdf_base64"] is not None
