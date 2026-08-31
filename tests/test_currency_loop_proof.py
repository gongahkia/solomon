# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from solomon.api.service import (
    AuthorityEventRequest,
    DependencyRequest,
    IngestRequest,
    RecallRequest,
    ReviewTaskAssignmentRequest,
    ReviewTaskResolutionRequest,
    ReviewTaskStartRequest,
    SolomonService,
    VerificationRequest,
)
from solomon.currency.engine import VerificationOutcome, VerificationPolicy
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.errors import BadRequestError
from solomon.graph.models import EdgeConfidence, EdgeType
from solomon.mcp.auth import MCP_READ_SCOPE, MCPPrincipal
from solomon.mcp.tools.runtime import SolomonMCPRuntime
from solomon.operations.failure_injection import OperationFailureInjector
from solomon.operations.models import OperationStatus

START = datetime(2026, 6, 1, tzinfo=timezone.utc)
CHANGE_AT = START + timedelta(days=1)
REVIEW_AT = START + timedelta(days=2)
AUTHORITY_ID = "authority:sg:capital-regulation:section-12"


def _service(tmp_path: Path) -> SolomonService:
    return SolomonService(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        verification_policy=VerificationPolicy(default_max_age_days=10_000, high_stakes_max_age_days=10_000),
    )


def _ingest(
    service: SolomonService,
    *,
    content: str,
    matter_id: str,
    client_id: str,
    timestamp: datetime = START,
) -> str:
    return service.ingest(
        IngestRequest(
            kind=KnowledgeKind.HOUSE_VIEW,
            content=content,
            source_kind=SourceKind.PARTNER,
            source_ref=f"fixture://{matter_id}/{content.split()[0].lower()}",
            author="partner-a",
            matter_id=matter_id,
            client_id=client_id,
            valid_from=timestamp,
            ingested_at=timestamp,
        )
    ).id


def _confirmed_authority_edge(service: SolomonService, item_id: str) -> None:
    service.add_dependency(
        DependencyRequest(
            source_id=item_id,
            target_id=AUTHORITY_ID,
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
            confidence=EdgeConfidence.HUMAN_CONFIRMED,
            created_by="lawyer-a",
            reason="confirmed citation to the official gazette section 12 version history",
        )
    )


def _authority_event() -> AuthorityEventRequest:
    return AuthorityEventRequest(
        source_id="official-gazette",
        idempotency_key="capital-regulation-section-12:v2",
        authority_id=AUTHORITY_ID,
        previous_version="2026-05-01",
        new_version="2026-06-02",
        changed_at=CHANGE_AT,
        evidence_url="https://gazette.example.test/capital-regulation/section-12/v2",
        evidence_sha256="9c5f25c2d2a95bd91189584253571f009e3bda18b023625dac83ac88f1a12ad2",
        diff={"changed_sections": ["12"], "summary": "synthetic currency-loop fixture"},
    )


def _alpha_principal() -> MCPPrincipal:
    return MCPPrincipal(
        subject="lawyer-alpha",
        role="lawyer",
        scopes=frozenset({MCP_READ_SCOPE}),
        matter_ids=frozenset({"matter-alpha"}),
        client_ids=frozenset({"client-alpha"}),
    )


def test_currency_loop_proof_covers_scope_impact_review_history_and_restart(tmp_path: Path) -> None:
    service = _service(tmp_path)
    direct_one = _ingest(
        service,
        content="Direct one currency-loop position relies on section 12.",
        matter_id="matter-alpha",
        client_id="client-alpha",
    )
    direct_two = _ingest(
        service,
        content="Direct two currency-loop position relies on section 12.",
        matter_id="matter-alpha",
        client_id="client-alpha",
    )
    transitive = _ingest(
        service,
        content="Transitive currency-loop advice relies on the direct one position.",
        matter_id="matter-alpha",
        client_id="client-alpha",
    )
    unrelated = _ingest(
        service,
        content="Unrelated currency-loop position belongs only to tenant bravo.",
        matter_id="matter-bravo",
        client_id="client-bravo",
    )
    _confirmed_authority_edge(service, direct_one)
    _confirmed_authority_edge(service, direct_two)
    service.add_dependency(
        DependencyRequest(
            source_id=transitive,
            target_id=direct_one,
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_INTERNAL,
            target_kind="knowledge_item",
            confidence=EdgeConfidence.HUMAN_CONFIRMED,
            created_by="lawyer-a",
            reason="confirmed downstream reliance in the reviewed advice",
        )
    )
    service.add_dependency(
        DependencyRequest(
            source_id=direct_one,
            target_id=transitive,
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_INTERNAL,
            target_kind="knowledge_item",
            confidence=EdgeConfidence.HUMAN_CONFIRMED,
            created_by="lawyer-a",
            reason="synthetic cycle probe; traversal must remain bounded",
        )
    )

    before = service.recall(RecallRequest(query="currency-loop", matter_id="matter-alpha", client_id="client-alpha"))
    registered = service.register_authority_event(_authority_event())
    duplicate = service.register_authority_event(_authority_event())
    runtime = SolomonMCPRuntime(service, principal=_alpha_principal())
    scoped_impact = runtime.impact(
        external_authority_id=AUTHORITY_ID,
        matter_id="matter-alpha",
        client_id="client-alpha",
    )
    denied_scope = runtime.impact(
        external_authority_id=AUTHORITY_ID,
        matter_id="matter-bravo",
        client_id="client-bravo",
    )
    default_after_change = runtime.preflight_context(
        query="currency-loop",
        matter_id="matter-alpha",
        client_id="client-alpha",
    )
    review_after_change = service.recall(
        RecallRequest(query="currency-loop", matter_id="matter-alpha", client_id="client-alpha", review_mode=True)
    )

    assert {result["item"]["id"] for result in before} == {direct_one, direct_two, transitive}
    assert registered["duplicate"] is False
    assert set(registered["impact"]["stale_item_ids"]) == {direct_one, direct_two, transitive}
    assert duplicate["duplicate"] is True
    assert set(scoped_impact["stale_item_ids"]) == {direct_one, direct_two, transitive}
    assert denied_scope["error"]["code"] == "authorization_denied"
    assert default_after_change["items"] == []
    assert {result["item"]["id"] for result in review_after_change} == {direct_one, direct_two, transitive}
    assert {reason["change_id"] for reason in review_after_change[0]["stale_reasons"]} == {registered["event"]["id"]}
    assert service.store.get_item(unrelated).currency_state.value == "Live"

    task_by_item = {task.item_id: task for task in service.review_tasks()}
    successor = _ingest(
        service,
        content="Successor currency-loop position applies the section 12 amendment.",
        matter_id="matter-alpha",
        client_id="client-alpha",
        timestamp=REVIEW_AT,
    )
    for item_id, task in task_by_item.items():
        service.assign_review_task(
            task.id,
            ReviewTaskAssignmentRequest(reviewer_id="lawyer-a", assigned_by="curator-a"),
        )
        service.start_review_task(task.id, ReviewTaskStartRequest(reviewer_id="lawyer-a"))
        outcome = VerificationOutcome.SUPERSEDE if item_id == direct_two else VerificationOutcome.REAFFIRM
        service.resolve_review_task(
            task.id,
            ReviewTaskResolutionRequest(
                reviewer_id="lawyer-a",
                verification=VerificationRequest(
                    by="lawyer-a",
                    outcome=outcome,
                    successor_id=successor if outcome is VerificationOutcome.SUPERSEDE else None,
                    basis="reviewed the official authority change",
                    source_ref="https://gazette.example.test/capital-regulation/section-12/v2",
                    recorded_at=REVIEW_AT,
                ),
            ),
        )

    restored = service.recall(RecallRequest(query="currency-loop", matter_id="matter-alpha", client_id="client-alpha"))
    historical = service.timeline(
        RecallRequest(query="currency-loop", matter_id="matter-alpha", client_id="client-alpha"),
        as_of=(CHANGE_AT - timedelta(seconds=1)).isoformat(),
    )
    pack = service.export_audit_pack(tmp_path / "audit-pack")

    assert {result["item"]["id"] for result in restored} == {direct_one, transitive, successor}
    assert service.store.get_item(direct_two).successor_id == successor
    assert {result["item"]["id"] for result in historical} == {direct_one, direct_two, transitive}
    assert unrelated not in {result["item"]["id"] for result in historical}
    assert service.audit.verify().ok is True
    assert (pack / "manifest.json").exists()
    assert service.audit.verify_pack(pack).ok is True

    restarted = _service(tmp_path)
    replayed = restarted.register_authority_event(_authority_event())
    stale_events = restarted.store.list_events(event_types={"knowledge_item_stale_flagged"})
    impact_entries = [entry for entry in restarted.audit.list_entries() if entry.event_type == "impact"]

    assert replayed["duplicate"] is True
    assert len(restarted.review_tasks()) == 3
    assert len(stale_events) == 3
    assert len(impact_entries) == 1


def test_incomplete_authority_event_retries_without_duplicate_propagation_or_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path)
    direct = _ingest(
        service,
        content="Recovery currency-loop position relies on section 12.",
        matter_id="matter-alpha",
        client_id="client-alpha",
    )
    _confirmed_authority_edge(service, direct)
    original_create_task = service.workflow_store.create_review_task

    def fail_once(*args: object, **kwargs: object) -> object:
        monkeypatch.setattr(service.workflow_store, "create_review_task", original_create_task)
        raise RuntimeError("simulated task-store interruption")

    monkeypatch.setattr(service.workflow_store, "create_review_task", fail_once)
    with pytest.raises(RuntimeError, match="simulated task-store interruption"):
        service.register_authority_event(_authority_event())

    recovered = service.register_authority_event(_authority_event())
    stale_events = service.store.list_events(event_types={"knowledge_item_stale_flagged"})
    impact_entries = [entry for entry in service.audit.list_entries() if entry.event_type == "impact"]

    assert recovered["duplicate"] is False
    assert service.workflow_store.authority_event_processed(recovered["event"]["id"]) is True
    assert service.workflow_store.authority_event_processing_error(recovered["event"]["id"]) is None
    assert len(service.review_tasks()) == 1
    assert len(stale_events) == 1
    assert len(impact_entries) == 1


@pytest.mark.parametrize("point", ["during_currency_propagation", "after_currency_before_audit"])
def test_currency_projection_interruption_resumes_without_duplicate_impact(tmp_path: Path, point: str) -> None:
    service = _service(tmp_path)
    direct = _ingest(
        service,
        content="Crash-safe currency-loop position relies on section 12.",
        matter_id="matter-alpha",
        client_id="client-alpha",
    )
    _confirmed_authority_edge(service, direct)
    service._authority.set_operation_failure_injector(OperationFailureInjector([point]))

    with pytest.raises(BadRequestError, match="durably queued"):
        service.register_authority_event(_authority_event())
    operation = next(
        current
        for current in service.operation_store.list()
        if current.operation_type.value == "authority_change_propagation"
    )
    assert operation.status is OperationStatus.RETRYING
    stale_before_restart = service.store.get_item(direct)
    assert len(stale_before_restart.metadata.get("staleness_reasons", [])) == (
        0 if point == "during_currency_propagation" else 1
    )

    service._authority.set_operation_failure_injector(OperationFailureInjector())
    assert operation.next_eligible_retry_at is not None
    recovered = service._authority.run_operation_once(
        worker_id="worker-restarted",
        now=operation.next_eligible_retry_at,
    )
    assert recovered is not None
    assert recovered.status is OperationStatus.COMPLETED
    stale_after_restart = service.store.get_item(direct)
    assert len(stale_after_restart.metadata["staleness_reasons"]) == 1
    impact_entries = [entry for entry in service.audit.list_entries() if entry.event_type == "impact"]
    assert len(impact_entries) == 1
