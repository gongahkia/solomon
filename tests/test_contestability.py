# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from solomon.api.service import AffirmRequest, ContestRequest, PinRequest, RecallRequest, SolomonService
from solomon.currency.models import CredenceTier, CurrencyState, KnowledgeItem, KnowledgeKind, Provenance, SourceKind
from solomon.errors import PolicyRefusalError
from solomon.graph.models import DependencyEdge, EdgeType


def test_contest_lowers_credence_audits_and_propagates_to_dependents(tmp_path: Path) -> None:
    service = _seed_service(tmp_path)

    response = service.contest(
        "item-1",
        ContestRequest(
            lawyer_id="Associate A",
            reason="Authority treatment looks wrong",
            proposed_correction="Corrected contested view under Regulation R section 12.",
            contested_at=_dt(2026),
        ),
    )

    contested = service.store.get_item("item-1")
    dependent = service.store.get_item("dependent-1")
    correction = response.correction_item
    review_results = service.recall(RecallRequest(query="contested view Regulation R", review_mode=True))
    raw_journal = (tmp_path / "journal" / "journal.jsonl").read_text(encoding="utf-8")

    assert contested.credence_tier is CredenceTier.UNVERIFIED
    assert contested.currency_state is CurrencyState.STALE_PENDING_REVERIFICATION
    assert contested.verified_state.value == "NeedsReview"
    assert contested.metadata["contests"][0]["reason"] == "Authority treatment looks wrong"
    assert dependent.currency_state is CurrencyState.STALE_PENDING_REVERIFICATION
    assert correction is not None
    assert correction.credence_tier is CredenceTier.UNVERIFIED
    assert correction.metadata["quarantined"] is True
    assert correction.metadata["proposed_correction_for"] == "item-1"
    assert any(result["item"]["id"] == "item-1" and result["item"]["metadata"]["contests"] for result in review_results)
    assert "contest" in raw_journal
    assert "Corrected contested view" not in raw_journal


def test_affirm_role_rules_and_correction_supersession(tmp_path: Path) -> None:
    service = _seed_service(tmp_path)
    contested = service.contest(
        "item-1",
        ContestRequest(
            lawyer_id="Associate A",
            reason="Needs correction",
            proposed_correction="Authoritative corrected view under Regulation R section 12.",
            contested_at=_dt(2026),
        ),
    )
    assert contested.correction_item is not None

    with pytest.raises(PolicyRefusalError, match="FirmAuthoritative"):
        service.affirm(
            "item-1",
            AffirmRequest(
                lawyer_id="Model agent",
                actor_tier=CredenceTier.MODEL_INFERRED,
                correction_item_id=contested.correction_item.id,
                affirmed_at=_dt(2026),
            ),
        )

    affirmed = service.affirm(
        "item-1",
        AffirmRequest(
            lawyer_id="Partner A",
            actor_tier=CredenceTier.FIRM_AUTHORITATIVE,
            correction_item_id=contested.correction_item.id,
            affirmed_at=_dt(2026),
        ),
    )

    assert affirmed.superseded is True
    assert affirmed.item.currency_state is CurrencyState.SUPERSEDED
    assert affirmed.correction_item is not None
    assert affirmed.correction_item.credence_tier is CredenceTier.FIRM_AUTHORITATIVE
    assert affirmed.correction_item.currency_state is CurrencyState.LIVE
    assert affirmed.correction_item.metadata["quarantined"] is False
    assert service.store.get_item("item-1").successor_id == affirmed.correction_item.id


def test_pin_requires_firm_authoritative_actor_and_sets_credence_floor(tmp_path: Path) -> None:
    service = _seed_service(tmp_path)

    with pytest.raises(PolicyRefusalError, match="FirmAuthoritative"):
        service.pin("item-1", PinRequest(lawyer_id="Associate A", actor_tier=CredenceTier.VERIFIED, reason="pin"))

    pinned = service.pin(
        "item-1",
        PinRequest(
            lawyer_id="Partner A",
            actor_tier=CredenceTier.FIRM_AUTHORITATIVE,
            reason="House view must not decay",
            pinned_at=_dt(2026),
        ),
    )

    assert pinned.credence_tier is CredenceTier.FIRM_AUTHORITATIVE
    assert pinned.metadata["credence_floor"] == "FirmAuthoritative"
    assert pinned.metadata["pinned_by"] == "Partner A"


def _seed_service(tmp_path: Path) -> SolomonService:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = _item("item-1", "Original contested view under Regulation R section 12.")
    dependent = _item("dependent-1", "Dependent memo that relies on item-1.")
    for candidate in (item, dependent):
        indexed = service.index.upsert_item(candidate)
        service.store.write_item(indexed)
    service.graph.add_dependency(
        DependencyEdge(
            id="edge-dependent",
            source_id="dependent-1",
            target_id="item-1",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_INTERNAL,
            target_kind="knowledge_item",
            valid_from=_dt(2025),
            created_at=_dt(2025),
        )
    )
    return service


def _item(item_id: str, content: str) -> KnowledgeItem:
    return KnowledgeItem(
        id=item_id,
        kind=KnowledgeKind.POSITION,
        content=content,
        provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref=item_id, author="Partner A"),
        valid_from=_dt(2025),
        ingested_at=_dt(2025),
        last_verified_at=_dt(2026),
        verified_by="Partner A",
        credence_tier=CredenceTier.FIRM_AUTHORITATIVE,
    )


def _dt(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)
