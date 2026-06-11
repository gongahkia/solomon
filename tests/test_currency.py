# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from solomon.currency.engine import (
    VerificationOutcome,
    VerificationPolicy,
    evaluate_currency,
    live_items,
    record_verification,
    register_authority_change,
    verification_due,
)
from solomon.currency.models import (
    CredenceTier,
    CurrencyState,
    KnowledgeItem,
    KnowledgeKind,
    Provenance,
    SourceKind,
)
from solomon.graph.models import DependencyEdge, EdgeType
from solomon.graph.store import GraphStore
from solomon.store.sqlite import SQLiteKnowledgeStore


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _item(item_id: str, *, verified_at: datetime | None = None) -> KnowledgeItem:
    return KnowledgeItem(
        id=item_id,
        kind=KnowledgeKind.HOUSE_VIEW,
        content="house view",
        provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref="memo", author="Partner A"),
        valid_from=_dt(2023, 1, 1),
        ingested_at=_dt(2023, 1, 1),
        credence_tier=CredenceTier.FIRM_AUTHORITATIVE,
        last_verified_at=verified_at,
        verified_by="Partner A" if verified_at else None,
    )


def test_evaluate_currency_uses_dependency_staleness_verification_and_validity() -> None:
    policy = VerificationPolicy(high_stakes_max_age_days=180)
    live = _item("item-1", verified_at=_dt(2025, 12, 1))
    stale = live.model_copy(update={"metadata": {"staleness_reasons": [{"dependency_id": "reg-r-12"}]}})
    superseded = live.model_copy(
        update={"valid_to": _dt(2025, 1, 1), "successor_id": "item-2", "currency_state": CurrencyState.SUPERSEDED}
    )

    assert evaluate_currency(live, as_of=_dt(2026, 1, 1), policy=policy).currency_state is CurrencyState.LIVE
    assert (
        evaluate_currency(stale, as_of=_dt(2026, 1, 1), policy=policy).currency_state
        is CurrencyState.STALE_PENDING_REVERIFICATION
    )
    assert (
        evaluate_currency(superseded, as_of=_dt(2026, 1, 1), policy=policy).currency_state
        is CurrencyState.SUPERSEDED
    )
    assert verification_due(_item("item-3"), as_of=_dt(2026, 1, 1), policy=policy) is True


def test_record_verification_reaffirms_retires_and_requires_successor_for_supersede() -> None:
    item = _item("item-1", verified_at=_dt(2023, 1, 1)).model_copy(
        update={
            "currency_state": CurrencyState.STALE_PENDING_REVERIFICATION,
            "metadata": {"staleness_reasons": [{"dependency_id": "reg-r-12"}]},
        }
    )

    reaffirmed = record_verification(
        item,
        by="Partner B",
        outcome=VerificationOutcome.REAFFIRM,
        recorded_at=_dt(2026, 1, 1),
    ).item
    retired = record_verification(item, by="Partner B", outcome="retire", recorded_at=_dt(2026, 1, 1)).item

    assert reaffirmed.currency_state is CurrencyState.LIVE
    assert "staleness_reasons" not in reaffirmed.metadata
    assert reaffirmed.verified_by == "Partner B"
    assert retired.currency_state is CurrencyState.RETIRED
    assert retired.valid_to == _dt(2026, 1, 1)
    with pytest.raises(ValueError, match="successor_id"):
        record_verification(item, by="Partner B", outcome="supersede", recorded_at=_dt(2026, 1, 1))


def test_live_items_default_query_path_filters_stale_and_superseded(tmp_path: Path) -> None:
    store = SQLiteKnowledgeStore(tmp_path / "solomon.sqlite3")
    live = _item("live", verified_at=_dt(2025, 12, 1))
    stale = _item("stale", verified_at=_dt(2025, 12, 1)).model_copy(
        update={"currency_state": CurrencyState.STALE_PENDING_REVERIFICATION}
    )
    store.write_item(live)
    store.write_item(stale)

    assert live_items(store) == [live]


def test_register_authority_change_triggers_graph_propagation(tmp_path: Path) -> None:
    db = tmp_path / "solomon.sqlite3"
    store = SQLiteKnowledgeStore(db)
    graph = GraphStore(db)
    store.write_item(_item("item-1", verified_at=_dt(2025, 1, 1)))
    graph.add_dependency(
        DependencyEdge(
            id="edge-1",
            source_id="item-1",
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
            valid_from=_dt(2023, 1, 1),
            created_at=_dt(2023, 1, 1),
        )
    )

    impact = register_authority_change(
        authority_id="reg-r-12",
        new_version="2025-amendment",
        changed_at=_dt(2025, 1, 1),
        graph=graph,
        store=store,
    )

    assert impact.stale_item_ids == ["item-1"]
    assert store.get_item("item-1").currency_state is CurrencyState.STALE_PENDING_REVERIFICATION
    assert "2025-amendment" in store.get_item("item-1").metadata["staleness_reasons"][0]["reason"]
