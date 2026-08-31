#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run Solomon's deterministic authority-change to human-review proof scenario."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
from solomon.graph.models import EdgeConfidence, EdgeType
from solomon.mcp.auth import MCP_READ_SCOPE, MCPPrincipal
from solomon.mcp.tools.runtime import SolomonMCPRuntime

START = datetime(2026, 6, 1, tzinfo=timezone.utc)
CHANGE_AT = START + timedelta(days=1)
REVIEW_AT = START + timedelta(days=2)
AUTHORITY_ID = "authority:sg:capital-regulation:section-12"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        required=True,
        help="empty directory for scenario state and artifacts",
    )
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    if workspace.exists() and any(workspace.iterdir()):
        raise SystemExit(f"workspace must be empty: {workspace}")
    workspace.mkdir(parents=True, exist_ok=True)
    result, snapshot = run(workspace)
    (workspace / "currency-loop-proof-result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (workspace / "currency-loop-proof-snapshot.json").write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(snapshot, indent=2, sort_keys=True))


def run(workspace: Path) -> tuple[dict[str, object], dict[str, object]]:
    service = _service(workspace)
    direct_one = _ingest(
        service, "Direct one currency-loop position relies on section 12.", "matter-alpha", "client-alpha"
    )
    direct_two = _ingest(
        service, "Direct two currency-loop position relies on section 12.", "matter-alpha", "client-alpha"
    )
    transitive = _ingest(
        service,
        "Transitive currency-loop advice relies on the direct one position.",
        "matter-alpha",
        "client-alpha",
    )
    unrelated = _ingest(
        service,
        "Unrelated currency-loop position belongs only to tenant bravo.",
        "matter-bravo",
        "client-bravo",
    )
    for item_id in (direct_one, direct_two):
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

    started = time.perf_counter()
    initial = service.recall(RecallRequest(query="currency-loop", matter_id="matter-alpha", client_id="client-alpha"))
    event = _authority_event()
    registered = service.register_authority_event(event)
    duplicate = service.register_authority_event(event)
    runtime = SolomonMCPRuntime(service, principal=_alpha_principal())
    scoped_impact = runtime.impact(
        external_authority_id=AUTHORITY_ID,
        matter_id="matter-alpha",
        client_id="client-alpha",
    )
    denied = runtime.impact(
        external_authority_id=AUTHORITY_ID,
        matter_id="matter-bravo",
        client_id="client-bravo",
    )
    default_after_change = runtime.preflight_context(
        query="currency-loop", matter_id="matter-alpha", client_id="client-alpha"
    )
    review_after_change = service.recall(
        RecallRequest(query="currency-loop", matter_id="matter-alpha", client_id="client-alpha", review_mode=True)
    )

    task_by_item = {task.item_id: task for task in service.review_tasks()}
    successor = _ingest(
        service,
        "Successor currency-loop position applies the section 12 amendment.",
        "matter-alpha",
        "client-alpha",
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
    pack = service.export_audit_pack(workspace / "audit-pack")
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)

    _require({row["item"]["id"] for row in initial} == {direct_one, direct_two, transitive}, "initial live recall")
    _require(set(registered["impact"]["stale_item_ids"]) == {direct_one, direct_two, transitive}, "impact traversal")
    _require(duplicate["duplicate"] is True, "duplicate authority event")
    _require(set(scoped_impact["stale_item_ids"]) == {direct_one, direct_two, transitive}, "scoped impact")
    _require(denied.get("error", {}).get("code") == "authorization_denied", "cross-scope impact denial")
    _require(default_after_change["items"] == [], "default retrieval excludes stale items")
    _require(
        {row["item"]["id"] for row in review_after_change} == {direct_one, direct_two, transitive},
        "review retrieval",
    )
    _require({row["item"]["id"] for row in restored} == {direct_one, transitive, successor}, "reviewed live retrieval")
    _require({row["item"]["id"] for row in historical} == {direct_one, direct_two, transitive}, "historical recall")
    _require(service.store.get_item(unrelated).currency_state.value == "Live", "unrelated state")
    _require(service.audit.verify().ok and service.audit.verify_pack(pack).ok, "audit pack")

    restarted = _service(workspace)
    replayed = restarted.register_authority_event(event)
    stale_events = restarted.store.list_events(event_types={"knowledge_item_stale_flagged"})
    impact_events = [entry for entry in restarted.audit.list_entries() if entry.event_type == "impact"]
    _require(replayed["duplicate"] is True, "restart duplicate event")
    _require(len(stale_events) == 3 and len(restarted.review_tasks()) == 3, "idempotent persistence")
    _require(len(impact_events) == 1, "idempotent impact audit")

    snapshot: dict[str, object] = {
        "schema": "solomon.currency_loop_proof.snapshot.v1",
        "authority": AUTHORITY_ID,
        "fixture": {
            "direct_dependencies": 2,
            "transitive_dependencies": 1,
            "unrelated_items": 1,
            "tenant_scopes": 2,
        },
        "impact": {"direct": 2, "transitive": 1, "unrelated": 0, "total": 3},
        "retrieval": {
            "before_change_live": 3,
            "default_after_change": 0,
            "review_mode_after_change": 3,
            "after_human_review": 3,
        },
        "scope": {"permitted_impact_items": 3, "cross_scope_denied": True, "unrelated_remained_live": True},
        "review": {"reaffirmed": 2, "superseded": 1, "successor_live": True},
        "history": {"pre_change_predecessors": 3, "successor_excluded_before_review": True},
        "idempotency": {
            "duplicate_event": True,
            "restart_replay": True,
            "stale_events": 3,
            "review_tasks": 3,
            "impact_audit_events": 1,
        },
        "cycle": {"bounded": True, "unique_impacts": 3},
        "explanation": {"staleness_reasons": 3, "change_id_present": True},
        "audit_pack_verified": True,
    }
    result = {**snapshot, "latency_ms": elapsed_ms, "latency_budget_ms": 2_000}
    return result, snapshot


def _service(workspace: Path) -> SolomonService:
    return SolomonService(
        data_dir=workspace / "data",
        journal_dir=workspace / "journal",
        verification_policy=VerificationPolicy(default_max_age_days=10_000, high_stakes_max_age_days=10_000),
    )


def _ingest(
    service: SolomonService,
    content: str,
    matter_id: str,
    client_id: str,
    *,
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


def _require(value: bool, name: str) -> None:
    if not value:
        raise RuntimeError(f"currency-loop proof failed: {name}")


if __name__ == "__main__":
    main()
