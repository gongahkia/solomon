# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest

from solomon.currency.models import now_utc
from solomon.operations.models import OperationPhase, OperationRecord, OperationScope, OperationStatus, OperationType
from solomon.operations.store import OperationConflictError, OperationNotFoundError, SQLiteOperationStore


def _operation(*, key: str = "assertion-1") -> OperationRecord:
    return OperationRecord(
        operation_type=OperationType.ASSERTION_CONFIRM,
        scope=OperationScope(tenant_id="tenant-a", matter_id="matter-a", client_id="client-a"),
        actor_id="reviewer-a",
        authorization_context={"role": "reviewer", "scope": "review"},
        correlation_id="correlation-a",
        idempotency_key=key,
        assertion_id="assertion-a",
        source_resource_id="source-document-a",
        source_version=1,
        requested_transition="confirmed",
        payload={"expected_state_version": 1},
    )


def test_operation_store_records_validated_append_only_transitions(tmp_path: Path) -> None:
    store = SQLiteOperationStore(tmp_path / "solomon.sqlite3")
    operation, created = store.create(_operation())
    assert created is True

    claimed = store.claim_next(worker_id="worker-a")
    assert claimed is not None
    assert claimed.status is OperationStatus.CLAIMED
    checkpoint = store.checkpoint(claimed.id, worker_id="worker-a", phase=OperationPhase.GRAPH, result_edge_id="edge-a")
    retrying = store.retry(
        checkpoint.id,
        worker_id="worker-a",
        retry_at=now_utc(),
        failure_category="transient_store",
        diagnostic="temporary graph failure\nwithout source content",
        maximum_attempts=3,
    )
    assert retrying.status is OperationStatus.RETRYING
    recovered = store.claim_next(worker_id="worker-b")
    assert recovered is not None
    completed = store.complete(recovered.id, worker_id="worker-b", result_edge_id="edge-a", audit_entry_hash="audit-a")

    assert completed.status is OperationStatus.COMPLETED
    assert completed.phase is OperationPhase.COMPLETED
    assert completed.result_edge_id == "edge-a"
    assert completed.audit_entry_hashes == ["audit-a"]
    assert [(entry.state_version, entry.event) for entry in store.history(operation.id)] == [
        (1, "created"),
        (2, "claimed"),
        (3, "checkpoint"),
        (4, "retry_scheduled"),
        (5, "claimed"),
        (6, "completed"),
    ]


def test_operation_idempotency_is_scoped_and_rejects_changed_immutable_request(tmp_path: Path) -> None:
    store = SQLiteOperationStore(tmp_path / "operations.sqlite3")
    operation, created = store.create(_operation())
    replay, replay_created = store.create(_operation())
    assert created is True
    assert replay_created is False
    assert replay.id == operation.id

    with pytest.raises(OperationConflictError, match="idempotency key"):
        store.create(_operation(key="assertion-1").model_copy(update={"requested_transition": "withdrawn"}))

    different_scope, created_in_different_scope = store.create(
        _operation().model_copy(update={"scope": OperationScope(tenant_id="tenant-b", matter_id="matter-a")})
    )
    assert created_in_different_scope is True
    assert different_scope.id != operation.id


def test_two_sqlite_workers_claim_one_operation_and_restart_reclaims_expired_lease(tmp_path: Path) -> None:
    path = tmp_path / "operations.sqlite3"
    first = SQLiteOperationStore(path)
    second = SQLiteOperationStore(path)
    operation, _ = first.create(_operation())
    timestamp = now_utc()

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(
            executor.map(
                lambda worker: (first if worker == "worker-a" else second).claim_next(
                    worker_id=worker,
                    lease_seconds=1,
                    now=timestamp,
                ),
                ("worker-a", "worker-b"),
            )
        )
    active = [claim for claim in claims if claim is not None]
    assert len(active) == 1
    assert active[0].id == operation.id

    restarted = SQLiteOperationStore(path)
    recovered = restarted.claim_next(worker_id="worker-restarted", now=timestamp + timedelta(seconds=2))
    assert recovered is not None
    assert recovered.id == operation.id
    assert recovered.attempt_count == 2
    assert restarted.history(operation.id)[-1].event == "reclaimed"


def test_terminal_operation_requires_explicit_manual_retry(tmp_path: Path) -> None:
    store = SQLiteOperationStore(tmp_path / "operations.sqlite3")
    operation, _ = store.create(_operation())
    claimed = store.claim_next(worker_id="worker-a")
    assert claimed is not None
    terminal = store.retry(
        operation.id,
        worker_id="worker-a",
        retry_at=now_utc(),
        failure_category="invariant",
        diagnostic="invalid source provenance",
        maximum_attempts=1,
    )
    assert terminal.status is OperationStatus.TERMINAL_FAILED
    assert store.claim_next(worker_id="worker-b") is None
    queued = store.manual_retry(operation.id, actor_id="operator-a")
    assert queued.status is OperationStatus.QUEUED
    assert store.history(operation.id)[-1].event == "manual_retry"


def test_operation_store_filters_counts_and_rejects_unowned_or_invalid_mutations(tmp_path: Path) -> None:
    store = SQLiteOperationStore(tmp_path / "operations.sqlite3")
    alpha, _ = store.create(_operation(key="alpha"))
    beta_scope = OperationScope(tenant_id="tenant-b", matter_id="matter-b", client_id="client-b")
    beta, _ = store.create(_operation(key="beta").model_copy(update={"scope": beta_scope}))
    timestamp = now_utc()

    assert [operation.id for operation in store.list(scope=alpha.scope)] == [alpha.id]
    assert [operation.id for operation in store.list(statuses={OperationStatus.QUEUED})] == [alpha.id, beta.id]
    assert store.list(statuses=set()) == []
    assert store.counts(now=timestamp, scope=alpha.scope)["queued"] == 1
    assert store.counts(now=timestamp, scope=alpha.scope)["oldest_pending_age_seconds"] >= 0.0
    with pytest.raises(ValueError, match="between"):
        store.list(limit=0)
    with pytest.raises(ValueError, match="positive lease"):
        store.claim_next(worker_id="", now=timestamp)
    with pytest.raises(OperationNotFoundError):
        store.get("missing-operation")
    with pytest.raises(OperationNotFoundError):
        store.history("missing-operation")

    claimed = store.claim_next(worker_id="worker-a", now=timestamp, scope=alpha.scope)
    assert claimed is not None and claimed.id == alpha.id
    assert store.claim_next(worker_id="worker-b", now=timestamp, scope=beta_scope).id == beta.id  # type: ignore[union-attr]
    with pytest.raises(OperationConflictError, match="not claimed"):
        store.checkpoint(alpha.id, worker_id="worker-b", phase=OperationPhase.GRAPH)
    with pytest.raises(OperationConflictError, match="not claimed"):
        store.complete(alpha.id, worker_id="worker-b")

    checkpoint = store.checkpoint(
        alpha.id,
        worker_id="worker-a",
        phase=OperationPhase.GRAPH,
        result_entity_id="assertion-a",
        result_edge_id="edge-a",
        audit_entry_hash="audit-a",
        now=timestamp,
    )
    repeated = store.checkpoint(
        alpha.id,
        worker_id="worker-a",
        phase=OperationPhase.GRAPH,
        audit_entry_hash="audit-a",
        now=timestamp,
    )
    assert checkpoint.audit_entry_hashes == repeated.audit_entry_hashes == ["audit-a"]
    retrying = store.retry(
        alpha.id,
        worker_id="worker-a",
        retry_at=timestamp + timedelta(seconds=10),
        failure_category="transient_store",
        diagnostic=("graph retry\n" + "x" * 600),
        maximum_attempts=3,
        now=timestamp,
    )
    assert retrying.status is OperationStatus.RETRYING
    assert retrying.diagnostic is not None and "\n" not in retrying.diagnostic and len(retrying.diagnostic) == 500
    assert store.claim_next(worker_id="worker-c", now=timestamp + timedelta(seconds=9), scope=alpha.scope) is None
    recovered = store.claim_next(worker_id="worker-c", now=timestamp + timedelta(seconds=10), scope=alpha.scope)
    assert recovered is not None and recovered.id == alpha.id


def test_operation_store_operator_resolution_and_model_transition_guards(tmp_path: Path) -> None:
    store = SQLiteOperationStore(tmp_path / "operations.sqlite3")
    operation, _ = store.create(_operation())
    claimed = store.claim_next(worker_id="worker-a")
    assert claimed is not None
    operator_required = store.require_operator(
        claimed.id,
        worker_id="worker-a",
        failure_category="provenance_invalid",
        diagnostic="candidate provenance cannot be reconstructed\nwithout evidence",
    )
    assert operator_required.status is OperationStatus.OPERATOR_REQUIRED
    assert operator_required.diagnostic == "candidate provenance cannot be reconstructed without evidence"
    assert store.claim_next(worker_id="worker-b") is None
    queued = store.manual_retry(operation.id, actor_id="operator-a")
    assert queued.status is OperationStatus.QUEUED
    with pytest.raises(OperationConflictError, match="only terminal"):
        store.manual_retry(operation.id, actor_id="operator-a")
    with pytest.raises(ValueError, match="invalid operation transition"):
        queued.with_transition(status=OperationStatus.COMPLETED)

    invalid_claim = _operation(key="invalid-claim").model_dump()
    invalid_claim.update({"status": OperationStatus.CLAIMED, "lease_owner": None, "lease_expires_at": None})
    with pytest.raises(ValueError, match="durable lease"):
        OperationRecord.model_validate(invalid_claim)
    invalid_context = _operation(key="invalid-context").model_dump()
    invalid_context["authorization_context"] = {"token": "not-recorded"}
    with pytest.raises(ValueError, match="credentials"):
        OperationRecord.model_validate(invalid_context)
