# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from solomon.currency.models import CredenceTier, CurrencyState, KnowledgeItem, KnowledgeKind, Provenance, SourceKind
from solomon.graph.models import DependencyEdge, EdgeType
from solomon.graph.propagation import CurrencyPropagator
from solomon.operations.models import OperationPhase, OperationRecord, OperationScope, OperationStatus, OperationType
from solomon.operations.postgres import PostgresOperationStore
from solomon.orchestrator.retrieval import MatterContext, RecallOptions, RetrievalOrchestrator
from solomon.store.factory import create_storage_bundle
from solomon.store.postgres import PostgresDependencyError

pytestmark = pytest.mark.integration


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _item(item_id: str, content: str, ingested_at: datetime | None = None) -> KnowledgeItem:
    timestamp = ingested_at or _dt(2024, 1, 1)
    return KnowledgeItem(
        id=item_id,
        kind=KnowledgeKind.POSITION,
        content=content,
        provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref=f"{item_id}.md"),
        valid_from=timestamp,
        ingested_at=timestamp,
        credence_tier=CredenceTier.FIRM_AUTHORITATIVE,
        last_verified_at=timestamp,
        verified_by="Partner A",
    )


def test_live_postgres_storage_bundle_matches_core_sqlite_workflow() -> None:
    dsn = os.environ.get("SOLOMON_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set SOLOMON_TEST_POSTGRES_DSN to run live Postgres integration coverage")

    psycopg = pytest.importorskip("psycopg")
    schema = f"test_solomon_{uuid.uuid4().hex}"
    bundle = None
    try:
        try:
            bundle = create_storage_bundle(dsn, postgres_schema=schema)
        except PostgresDependencyError as exc:
            pytest.skip(str(exc))
        orchestrator = RetrievalOrchestrator(store=bundle.store, graph=bundle.graph, index=bundle.index)

        predecessor = _item("item-1", "2023 structure x under regulation r section 12", _dt(2023, 1, 1))
        successor = _item("item-2", "2025 replacement structure x view", _dt(2025, 1, 1))
        indexed_predecessor = bundle.index.upsert_item(predecessor)
        bundle.store.write_item(indexed_predecessor)
        closed, written_successor = bundle.store.supersede(
            predecessor.id,
            bundle.index.upsert_item(successor),
            superseded_at=_dt(2025, 1, 1),
        )
        bundle.graph.add_dependency(
            DependencyEdge(
                id="edge-1",
                source_id=written_successor.id,
                target_id="reg-r-12",
                edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
                target_kind="external_authority",
                created_at=_dt(2025, 1, 1),
                valid_from=_dt(2025, 1, 1),
            )
        )

        recall = orchestrator.recall(
            "replacement structure regulation",
            matter_context=MatterContext(),
            options=RecallOptions(review_mode=True),
        )
        impact = CurrencyPropagator(graph=bundle.graph, store=bundle.store).propagate_dependency_change(
            "reg-r-12",
            changed_at=_dt(2026, 1, 1),
            reason="Live Postgres integration authority change",
        )

        assert closed.currency_state is CurrencyState.SUPERSEDED
        assert bundle.store.get_item(predecessor.id).successor_id == successor.id
        assert [item.id for item in bundle.store.as_of(_dt(2024, 1, 1))] == [predecessor.id]
        assert recall[0].item.id == written_successor.id
        assert impact.stale_item_ids == [written_successor.id]
        assert bundle.store.get_item(written_successor.id).currency_state is CurrencyState.STALE_PENDING_REVERIFICATION
    finally:
        if bundle is not None:
            bundle.store.close()
            bundle.graph.close()
            bundle.index.close()
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def test_live_postgres_operation_journal_claims_once_and_preserves_history() -> None:
    dsn = os.environ.get("SOLOMON_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set SOLOMON_TEST_POSTGRES_DSN to run live Postgres integration coverage")

    psycopg = pytest.importorskip("psycopg")
    schema = f"test_operations_{uuid.uuid4().hex}"
    first = second = None
    try:
        first = PostgresOperationStore(dsn, schema=schema)
        second = PostgresOperationStore(dsn, schema=schema)
        operation, created = first.create(
            OperationRecord(
                operation_type=OperationType.ASSERTION_CONFIRM,
                scope=OperationScope(tenant_id="tenant-a", matter_id="matter-a", client_id="client-a"),
                actor_id="reviewer-a",
                authorization_context={"service_access": "review"},
                correlation_id="postgres-operation-test",
                idempotency_key="assertion-confirm:postgres-test",
                assertion_id="assertion-a",
                requested_transition="confirmed",
            )
        )
        assert created is True

        with ThreadPoolExecutor(max_workers=2) as executor:
            claimed = list(
                executor.map(
                    lambda store: store.claim_next(worker_id=f"worker-{id(store)}"),
                    (first, second),
                )
            )
        claimed_once = [current for current in claimed if current is not None]
        assert len(claimed_once) == 1
        active = claimed_once[0]
        assert active.id == operation.id
        assert active.lease_owner is not None

        checkpointed = first.checkpoint(
            active.id,
            worker_id=active.lease_owner,
            phase=OperationPhase.GRAPH,
            result_entity_id="assertion-a",
            result_edge_id="edge-a",
        )
        completed = first.complete(
            checkpointed.id,
            worker_id=active.lease_owner,
            result_entity_id="assertion-a",
            result_edge_id="edge-a",
        )
        assert completed.status is OperationStatus.COMPLETED
        assert [entry.event for entry in second.history(operation.id)] == [
            "created",
            "claimed",
            "checkpoint",
            "completed",
        ]
        with psycopg.connect(dsn) as conn:
            row = conn.execute(
                f'SELECT version FROM "{schema}".schema_migrations WHERE scope = %s',  # noqa: S608
                ("operation-store",),
            ).fetchone()
        assert row == (1,)
    finally:
        if first is not None:
            first.close()
        if second is not None:
            second.close()
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
