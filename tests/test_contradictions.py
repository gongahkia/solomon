# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from solomon.api.service import DependencyRequest, IngestRequest, RecallRequest, SolomonService
from solomon.audit.journal import AuditJournal
from solomon.currency.contradiction import ConclusionPolarity, detect_same_authority_opposite_conclusions
from solomon.currency.models import (
    CredenceTier,
    CurrencyState,
    KnowledgeItem,
    KnowledgeKind,
    Provenance,
    SourceKind,
    VerifiedState,
)
from solomon.graph.models import DependencyEdge, EdgeType
from solomon.graph.store import GraphStore
from solomon.store.sqlite import SQLiteKnowledgeStore


def test_same_authority_opposite_conclusions_flags_both_and_surfaces_in_audit_pack(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    allow = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="Structure X may rely on Regulation R section 12.",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-allow",
            matter_id="matter-a",
            client_id="client-a",
            conclusion="Structure X may rely on Regulation R section 12.",
            conclusion_polarity=ConclusionPolarity.AFFIRMATIVE,
        )
    )
    deny = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="Structure X may not rely on Regulation R section 12.",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-deny",
            matter_id="matter-a",
            client_id="client-a",
            conclusion="Structure X may not rely on Regulation R section 12.",
            conclusion_polarity=ConclusionPolarity.NEGATIVE,
        )
    )
    _depends_on(service, allow.id, "reg-r-12")
    _depends_on(service, deny.id, "reg-r-12")

    allow_trace = service.why(allow.id)
    deny_trace = service.why(deny.id)
    assert allow_trace.currency["currency_state"] == "StalePendingReverification"
    assert deny_trace.currency["currency_state"] == "StalePendingReverification"
    assert allow_trace.item.successor_id is None
    assert deny_trace.item.successor_id is None
    assert allow_trace.contradictions[0]["conflicting_item_id"] == deny.id
    assert deny_trace.contradictions[0]["conflicting_item_id"] == allow.id
    assert service.verification_queue(matter_id="matter-a")[0]["item"]["id"] in {allow.id, deny.id}

    review_results = service.recall(RecallRequest(query="Structure X Regulation R", review_mode=True, limit=5))
    contradiction_counts = {
        result["item"]["id"]: len(result["contradictions"])
        for result in review_results
        if result["item"]["id"] in {allow.id, deny.id}
    }
    assert contradiction_counts == {allow.id: 1, deny.id: 1}
    assert "contradiction_detected" in service.audit.path.read_text(encoding="utf-8")

    pack_dir = service.export_audit_pack(tmp_path / "pack")
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    contradiction_payload = json.loads((pack_dir / manifest["contradictions_file"]).read_text(encoding="utf-8"))
    assert contradiction_payload[allow.id][0]["conflicting_item_id"] == deny.id
    assert AuditJournal.verify_pack(pack_dir).ok is True


@given(
    left=st.sampled_from([ConclusionPolarity.AFFIRMATIVE, ConclusionPolarity.NEGATIVE]),
    right=st.sampled_from([ConclusionPolarity.AFFIRMATIVE, ConclusionPolarity.NEGATIVE]),
    successor_pair=st.booleans(),
)
@settings(max_examples=20)
def test_contradiction_detection_is_symmetric_and_skips_successor_pairs(
    left: ConclusionPolarity,
    right: ConclusionPolarity,
    successor_pair: bool,
) -> None:
    with tempfile.TemporaryDirectory(prefix="solomon-contradiction-property-") as tmp:
        db = Path(tmp) / "solomon.sqlite3"
        store = SQLiteKnowledgeStore(db)
        graph = GraphStore(db)
        left_item = _position("left", left, successor_id="right" if successor_pair else None)
        right_item = _position("right", right, supersedes="left" if successor_pair else None)
        store.write_item(left_item)
        store.write_item(right_item)
        graph.add_dependency(_edge("left", "authority-a"))
        graph.add_dependency(_edge("right", "authority-a"))

        signals = detect_same_authority_opposite_conclusions(store=store, graph=graph)
        pairs = {(signal.item_id, signal.conflicting_item_id) for signal in signals}
        if successor_pair or left is right:
            assert pairs == set()
        else:
            assert pairs == {("left", "right"), ("right", "left")}


def _depends_on(service: SolomonService, item_id: str, authority_id: str) -> None:
    service.add_dependency(
        DependencyRequest(
            source_id=item_id,
            target_id=authority_id,
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )


def _dt() -> datetime:
    return datetime(2026, 7, 10, tzinfo=timezone.utc)


def _position(
    item_id: str,
    polarity: ConclusionPolarity,
    *,
    successor_id: str | None = None,
    supersedes: str | None = None,
) -> KnowledgeItem:
    metadata = {"conclusion": f"{item_id} conclusion", "conclusion_polarity": polarity.value}
    if supersedes is not None:
        metadata["supersedes"] = supersedes
    return KnowledgeItem(
        id=item_id,
        kind=KnowledgeKind.POSITION,
        content=f"{item_id} content",
        provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref=item_id),
        valid_from=_dt(),
        ingested_at=_dt(),
        credence_tier=CredenceTier.FIRM_AUTHORITATIVE,
        currency_state=CurrencyState.LIVE,
        verified_state=VerifiedState.VERIFIED,
        last_verified_at=_dt(),
        successor_id=successor_id,
        metadata=metadata,
    )


def _edge(source_id: str, target_id: str) -> DependencyEdge:
    return DependencyEdge(
        source_id=source_id,
        target_id=target_id,
        edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
        target_kind="external_authority",
    )
