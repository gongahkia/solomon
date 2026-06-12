# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from solomon.credence.policy import CredenceLedger
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
from solomon.orchestrator.retrieval import (
    EmbeddingStrategy,
    MatterContext,
    RecallOptions,
    RetrievalOrchestrator,
    SQLiteRetrievalIndex,
)
from solomon.store.sqlite import SQLiteKnowledgeStore


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _item(
    item_id: str,
    content: str,
    *,
    tier: CredenceTier = CredenceTier.VERIFIED,
    state: CurrencyState = CurrencyState.LIVE,
    matter_id: str | None = None,
) -> KnowledgeItem:
    return KnowledgeItem(
        id=item_id,
        kind=KnowledgeKind.POSITION,
        content=content,
        provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref=item_id),
        valid_from=_dt(2023, 1, 1),
        ingested_at=_dt(2023, 1, 1),
        last_verified_at=_dt(2026, 1, 1),
        credence_tier=tier,
        currency_state=state,
        matter_id=matter_id,
    )


def _orchestrator(tmp_path: Path) -> RetrievalOrchestrator:
    db = tmp_path / "solomon.sqlite3"
    return RetrievalOrchestrator(
        store=SQLiteKnowledgeStore(db),
        graph=GraphStore(db),
        index=SQLiteRetrievalIndex(db),
        credence=CredenceLedger(),
    )


def test_recall_returns_live_items_by_default_and_stale_in_review_mode(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    live = _item("live", "structure x regulation r section 12")
    stale = _item("stale", "structure x regulation r section 12", state=CurrencyState.STALE_PENDING_REVERIFICATION)
    orchestrator.store.write_item(live)
    orchestrator.store.write_item(stale)
    orchestrator.index_items([live, stale])

    default = orchestrator.recall("structure x regulation")
    review = orchestrator.recall(
        "structure x regulation",
        options=RecallOptions(review_mode=True, dedupe_near_identical=False),
    )

    assert [result.item.id for result in default] == ["live"]
    assert {result.item.id for result in review} == {"live", "stale"}


def test_recall_filters_on_computed_currency_and_output_matches_displayed_state(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    stale_by_policy = _item("computed-stale", "structure x needs verification").model_copy(
        update={"last_verified_at": None}
    )
    orchestrator.store.write_item(stale_by_policy)
    orchestrator.index_items([stale_by_policy])

    default = orchestrator.recall("structure x")
    review = orchestrator.recall("structure x", options=RecallOptions(review_mode=True))

    assert default == []
    assert review[0].currency_state is CurrencyState.STALE_PENDING_REVERIFICATION
    assert review[0].item.currency_state is review[0].currency_state


def test_recall_attaches_dependencies_provenance_currency_and_last_verified(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    item = _item("item-1", "house view depends on regulation r section 12")
    edge = DependencyEdge(
        id="edge-1",
        source_id="item-1",
        target_id="reg-r-12",
        edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
        target_kind="external_authority",
        valid_from=_dt(2023, 1, 1),
        created_at=_dt(2023, 1, 1),
    )
    orchestrator.store.write_item(item)
    orchestrator.graph.add_dependency(edge)
    orchestrator.index_items([item])

    result = orchestrator.recall("regulation r section 12")[0]

    assert result.currency_state is CurrencyState.LIVE
    assert result.provenance["source_ref"] == "item-1"
    assert result.dependencies[0].id == "edge-1"
    assert result.last_verified_at == _dt(2026, 1, 1)


def test_credence_guardrail_and_dedupe_affect_ranking(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    firm = _item("firm", "same position alpha", tier=CredenceTier.FIRM_AUTHORITATIVE)
    model = _item("model", "same position alpha", tier=CredenceTier.MODEL_INFERRED)
    orchestrator.store.write_item(firm)
    orchestrator.store.write_item(model)
    orchestrator.index_items([firm, model])

    result = orchestrator.recall("same position alpha")

    assert [entry.item.id for entry in result] == ["firm"]


def test_timeline_uses_historical_state(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    old = _item("old", "structure x allowed under old rule")
    new = _item("new", "structure x requires review under new rule")
    orchestrator.store.write_item(old)
    orchestrator.store.supersede("old", new, superseded_at=_dt(2025, 1, 1))

    before = orchestrator.timeline("structure x allowed", as_of=_dt(2024, 1, 1))
    after = orchestrator.timeline("structure x review", as_of=_dt(2026, 1, 1))

    assert [result.item.id for result in before] == ["old"]
    assert {result.item.id for result in after} == {"old", "new"}


def test_batch_index_stores_embedding_ref_and_scope_filtering(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    a = _item("a", "client a structure x", matter_id="matter-a")
    b = _item("b", "client b structure x", matter_id="matter-b")
    orchestrator.store.write_item(a)
    orchestrator.store.write_item(b)
    indexed = orchestrator.index_items([a, b])

    scoped = orchestrator.recall("structure x", matter_context=MatterContext(matter_id="matter-a"))

    assert all(item.embedding_ref == "lexical-token-set:1" for item in indexed)
    assert [result.item.id for result in scoped] == ["a"]


def test_reembed_pipeline_updates_items_when_strategy_version_changes(tmp_path: Path) -> None:
    db = tmp_path / "solomon.sqlite3"
    item = _item("item-1", "structure x regulation r")
    first = RetrievalOrchestrator(
        store=SQLiteKnowledgeStore(db),
        graph=GraphStore(db),
        index=SQLiteRetrievalIndex(db, strategy=EmbeddingStrategy(version="1")),
        credence=CredenceLedger(),
    )
    first.store.write_item(item)
    first.index_items([item])

    second = RetrievalOrchestrator(
        store=SQLiteKnowledgeStore(db),
        graph=GraphStore(db),
        index=SQLiteRetrievalIndex(db, strategy=EmbeddingStrategy(version="2")),
        credence=CredenceLedger(),
    )

    report = second.reembed_stale_items()
    noop = second.reembed_stale_items()

    assert report.embedding_ref == "lexical-token-set:2"
    assert report.considered_item_ids == ["item-1"]
    assert report.reembedded_item_ids == ["item-1"]
    assert second.store.get_item("item-1").embedding_ref == "lexical-token-set:2"
    assert second.index.search("structure x")[0].embedding_ref == "lexical-token-set:2"
    assert noop.reembedded_item_ids == []


def test_recall_context_budget_caps_results_before_sanitisation(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    short = _item("short", "alpha beta")
    long = _item("long", "alpha beta gamma delta")
    orchestrator.store.write_item(short)
    orchestrator.store.write_item(long)
    orchestrator.index_items([short, long])

    results = orchestrator.recall(
        "alpha beta",
        options=RecallOptions(max_context_tokens=2, dedupe_near_identical=False),
    )

    assert [result.item.id for result in results] == ["short"]
    assert sum(result.estimated_context_tokens for result in results) <= 2
