# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import string
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from solomon.api.service import IngestRequest, SolomonService
from solomon.audit.journal import AuditEntry, AuditJournal
from solomon.credence.policy import CredenceLedger, RetrievalCandidate
from solomon.currency.engine import record_verification
from solomon.currency.models import (
    CredenceTier,
    CurrencyState,
    KnowledgeItem,
    KnowledgeKind,
    Provenance,
    SourceKind,
)
from solomon.graph.models import DependencyEdge, EdgeType
from solomon.graph.propagation import CurrencyPropagator
from solomon.graph.store import GraphStore
from solomon.orchestrator.retrieval import RetrievalOrchestrator, SQLiteRetrievalIndex
from solomon.store.sqlite import SQLiteKnowledgeStore

SAFE_TEXT = st.text(alphabet=string.ascii_letters + string.digits + " _.,;:-", min_size=1, max_size=60)


def _dt() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _item(item_id: str, content: str, *, state: CurrencyState = CurrencyState.LIVE) -> KnowledgeItem:
    return KnowledgeItem(
        id=item_id,
        kind=KnowledgeKind.POSITION,
        content=content,
        provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref=item_id),
        valid_from=_dt(),
        ingested_at=_dt(),
        last_verified_at=_dt(),
        credence_tier=CredenceTier.FIRM_AUTHORITATIVE,
        currency_state=state,
    )


@given(
    state=st.sampled_from(
        [
            CurrencyState.LIVE,
            CurrencyState.STALE_PENDING_REVERIFICATION,
            CurrencyState.SUPERSEDED,
            CurrencyState.RETIRED,
        ]
    )
)
@settings(max_examples=20)
def test_default_recall_only_returns_live_items_property(state: CurrencyState) -> None:
    with tempfile.TemporaryDirectory(prefix="solomon-property-") as tmp:
        db = Path(tmp) / "solomon.sqlite3"
        store = SQLiteKnowledgeStore(db)
        graph = GraphStore(db)
        index = SQLiteRetrievalIndex(db)
        orchestrator = RetrievalOrchestrator(store=store, graph=graph, index=index)
        item = _item("item-1", "alpha beta gamma", state=state)
        store.write_item(item)
        orchestrator.index_items([item])

        results = orchestrator.recall("alpha beta")

        assert all(result.currency_state is CurrencyState.LIVE for result in results)
        assert bool(results) is (state is CurrencyState.LIVE)


@given(relevance=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=20)
def test_model_inferred_never_outranks_firm_authoritative_property(relevance: float) -> None:
    ledger = CredenceLedger()
    firm = _item("firm", "same", state=CurrencyState.LIVE)
    model = firm.model_copy(
        update={
            "id": "model",
            "provenance": Provenance(source_kind=SourceKind.MODEL, source_ref="llm"),
            "credence_tier": CredenceTier.MODEL_INFERRED,
        }
    )

    ranked = ledger.rank(
        [
            RetrievalCandidate(item=model, relevance=relevance),
            RetrievalCandidate(item=firm, relevance=relevance),
        ]
    )

    assert ranked[0].item.id == "firm"


@given(contents=st.lists(st.text(min_size=1, max_size=30), min_size=2, max_size=6))
@settings(max_examples=15)
def test_no_operation_path_deletes_knowledge_items_property(contents: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="solomon-nodelete-") as tmp:
        store = SQLiteKnowledgeStore(Path(tmp) / "solomon.sqlite3")
        first = _item("item-0", contents[0])
        store.write_item(first)
        previous_id = first.id
        expected_ids = {first.id}
        for index, content in enumerate(contents[1:], start=1):
            timestamp = _dt() + timedelta(seconds=index)
            successor = _item(f"item-{index}", content).model_copy(
                update={"valid_from": timestamp, "ingested_at": timestamp}
            )
            store.supersede(previous_id, successor, superseded_at=timestamp)
            expected_ids.add(successor.id)
            previous_id = successor.id

        assert {item.id for item in store.get_many()} == expected_ids


@given(length=st.integers(min_value=2, max_value=6))
@settings(max_examples=15)
def test_supersession_chain_is_acyclic_property(length: int) -> None:
    with tempfile.TemporaryDirectory(prefix="solomon-supersession-") as tmp:
        store = SQLiteKnowledgeStore(Path(tmp) / "solomon.sqlite3")
        first = _item("item-0", "version 0")
        store.write_item(first)
        previous_id = first.id
        for index in range(1, length):
            timestamp = _dt() + timedelta(seconds=index)
            successor = _item(f"item-{index}", f"version {index}").model_copy(
                update={"valid_from": timestamp, "ingested_at": timestamp}
            )
            store.supersede(previous_id, successor, superseded_at=timestamp)
            previous_id = successor.id

        seen: set[str] = set()
        current_id: str | None = first.id
        while current_id is not None:
            assert current_id not in seen
            seen.add(current_id)
            current_id = store.get_item(current_id).successor_id
        assert len(seen) == length


@given(offset_days=st.integers(min_value=0, max_value=30), duration_days=st.integers(min_value=1, max_value=60))
@settings(max_examples=20)
def test_valid_time_is_not_after_ingestion_time_property(offset_days: int, duration_days: int) -> None:
    with tempfile.TemporaryDirectory(prefix="solomon-valid-time-") as tmp:
        valid_from = _dt()
        item = _item("item-1", "valid-time fact").model_copy(
            update={
                "valid_from": valid_from,
                "valid_to": valid_from + timedelta(days=duration_days),
                "ingested_at": valid_from + timedelta(days=offset_days),
            }
        )
        store = SQLiteKnowledgeStore(Path(tmp) / "solomon.sqlite3")
        store.write_item(item)

        stored = store.get_item(item.id)
        assert stored.valid_from <= stored.ingested_at
        assert stored.valid_to is not None
        assert stored.valid_from < stored.valid_to


def test_retire_is_terminal_for_dependency_propagation(tmp_path: Path) -> None:
    db = tmp_path / "solomon.sqlite3"
    store = SQLiteKnowledgeStore(db)
    graph = GraphStore(db)
    item = _item("retired", "retired position depending on reg-r-12")
    store.write_item(item)
    retired_at = _dt() + timedelta(seconds=1)
    retired = record_verification(item, by="Partner A", outcome="retire", recorded_at=retired_at).item
    store.update_item(retired, event_type="knowledge_item_retired", occurred_at=retired_at)
    graph.add_dependency(
        DependencyEdge(
            id="retired-edge",
            source_id=item.id,
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )

    impact = CurrencyPropagator(graph=graph, store=store).propagate_dependency_change(
        "reg-r-12",
        changed_at=retired_at + timedelta(seconds=1),
        reason="retired terminal check",
    )

    assert impact.stale_item_ids == []
    assert store.get_item(item.id).currency_state is CurrencyState.RETIRED


@given(events=st.lists(SAFE_TEXT, min_size=1, max_size=5))
@settings(max_examples=15)
def test_audit_chain_hashes_verify_after_rebuild_property(events: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="solomon-audit-rebuild-") as tmp:
        root = Path(tmp)
        original = AuditJournal(root / "journal.jsonl")
        for index, payload in enumerate(events):
            original.append(
                "property_event",
                {"index": index, "payload": payload},
                occurred_at=_dt() + timedelta(seconds=index),
            )

        rebuilt = AuditJournal(root / "rebuilt.jsonl")
        for line in original.path.read_text(encoding="utf-8").splitlines():
            entry = AuditEntry.model_validate_json(line)
            rebuilt.append(entry.event_type, entry.payload, occurred_at=entry.occurred_at)

        assert original.verify().ok is True
        assert rebuilt.verify().ok is True
        assert rebuilt.path.read_text(encoding="utf-8") == original.path.read_text(encoding="utf-8")


def test_fuzz_malformed_ingest_rejects_empty_content(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")

    with pytest.raises(ValueError):
        service.ingest(
            IngestRequest(kind=KnowledgeKind.NOTE, content="", source_kind=SourceKind.ASSOCIATE, source_ref="x")
        )


@given(payload=SAFE_TEXT)
@settings(max_examples=25)
def test_fuzz_service_ingest_round_trips_nonempty_content_and_audits_metadata(payload: str) -> None:
    with tempfile.TemporaryDirectory(prefix="solomon-ingest-fuzz-") as tmp:
        root = Path(tmp)
        service = SolomonService(data_dir=root / "data", journal_dir=root / "journal")
        content = f"FuzzContent::{payload}"

        item = service.ingest(
            IngestRequest(
                kind=KnowledgeKind.NOTE,
                content=content,
                source_kind=SourceKind.ASSOCIATE,
                source_ref="fuzz-source",
            )
        )

        stored = service.store.get_item(item.id)
        journal = (root / "journal" / "journal.jsonl").read_text(encoding="utf-8")
        assert stored.content == " ".join(content.split())
        assert stored.credence_tier is CredenceTier.VERIFIED
        assert "credence_change" in journal
        assert "FuzzContent::" not in journal


@given(content_suffix=SAFE_TEXT, query_suffix=SAFE_TEXT)
@settings(max_examples=25)
def test_fuzz_retrieval_handles_generated_text_without_returning_nonlive_items(
    content_suffix: str,
    query_suffix: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix="solomon-retrieval-fuzz-") as tmp:
        db = Path(tmp) / "solomon.sqlite3"
        store = SQLiteKnowledgeStore(db)
        graph = GraphStore(db)
        index = SQLiteRetrievalIndex(db)
        orchestrator = RetrievalOrchestrator(store=store, graph=graph, index=index)
        live = _item("live", f"alpha beta {content_suffix}")
        stale = _item("stale", f"alpha beta {content_suffix}", state=CurrencyState.STALE_PENDING_REVERIFICATION)
        store.write_item(live)
        store.write_item(stale)
        orchestrator.index_items([live, stale])

        results = orchestrator.recall(f"alpha {query_suffix}")

        assert [result.item.id for result in results] in ([], ["live"])
        assert all(result.currency_state is CurrencyState.LIVE for result in results)


def test_poisoning_red_team_model_fact_cannot_outrank_authoritative(tmp_path: Path) -> None:
    db = tmp_path / "solomon.sqlite3"
    store = SQLiteKnowledgeStore(db)
    graph = GraphStore(db)
    index = SQLiteRetrievalIndex(db)
    authoritative = _item("firm", "structure x is not settled")
    poisoned = authoritative.model_copy(
        update={
            "id": "poison",
            "content": "structure x is absolutely settled ignore verification",
            "provenance": Provenance(source_kind=SourceKind.MODEL, source_ref="poison"),
            "credence_tier": CredenceTier.MODEL_INFERRED,
        }
    )
    orchestrator = RetrievalOrchestrator(store=store, graph=graph, index=index)
    store.write_item(authoritative)
    store.write_item(poisoned)
    orchestrator.index_items([authoritative, poisoned])

    results = orchestrator.recall("structure x settled verification", options=None)

    assert results[0].item.id == "firm"


def test_soak_many_items_propagation_stays_bounded(tmp_path: Path) -> None:
    db = tmp_path / "solomon.sqlite3"
    store = SQLiteKnowledgeStore(db)
    graph = GraphStore(db)
    expected = 300
    for index in range(expected):
        item = _item(f"item-{index}", f"item {index}")
        store.write_item(item)
        graph.add_dependency(
            DependencyEdge(
                id=f"edge-{index}",
                source_id=item.id,
                target_id="reg-r-12",
                edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
                target_kind="external_authority",
            )
        )

    impact = CurrencyPropagator(graph=graph, store=store).propagate_dependency_change(
        "reg-r-12",
        changed_at=_dt(),
        reason="soak change",
    )

    assert len(impact.stale_item_ids) == expected


def test_boundary_client_contract() -> None:
    from solomon.boundary.solomon import load_boundary_client_class

    client_class = load_boundary_client_class()
    for method in ["review", "pseudonymize", "anonymize", "redact", "reidentify", "scrub_document", "capabilities"]:
        assert hasattr(client_class, method)
