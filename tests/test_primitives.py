# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from solomon.api.service import PrimitivePlanRequest, PrimitivePlanStep, SolomonService
from solomon.currency.models import CredenceTier, KnowledgeItem, KnowledgeKind, Provenance, SourceKind, VerifiedState
from solomon.errors import BadRequestError
from solomon.graph.models import DependencyEdge, EdgeType


def test_primitive_plan_reexecutes_deterministically(tmp_path: Path) -> None:
    service = _seed_service(tmp_path / "one")
    other = _seed_service(tmp_path / "two")
    plan = _read_plan()

    first = service.execute_plan(plan)
    replayed = service.execute_plan(first.plan)
    same_state = other.execute_plan(plan)

    assert first.store_state_sha256 == replayed.store_state_sha256 == same_state.store_state_sha256
    assert [step.result_sha256 for step in first.steps] == [step.result_sha256 for step in replayed.steps]
    assert [step.result_sha256 for step in first.steps] == [step.result_sha256 for step in same_state.steps]
    assert first.steps[0].result[0]["item"]["id"] == "item-1"


def test_primitive_plan_rejects_unsanctioned_step(tmp_path: Path) -> None:
    service = _seed_service(tmp_path)

    with pytest.raises(BadRequestError, match="unsupported primitive"):
        service.execute_plan(
            PrimitivePlanRequest(steps=[PrimitivePlanStep(primitive="shell", args={"cmd": "rm -rf /"})])
        )


def test_primitive_plan_audit_is_metadata_only(tmp_path: Path) -> None:
    service = _seed_service(tmp_path)

    service.execute_plan(_read_plan())

    raw = (tmp_path / "journal" / "journal.jsonl").read_text(encoding="utf-8")
    assert "primitive_plan" in raw
    assert "result_sha256" in raw
    assert "privileged plan content" not in raw


def _seed_service(root: Path) -> SolomonService:
    service = SolomonService(data_dir=root / "data", journal_dir=root / "journal")
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    item = KnowledgeItem(
        id="item-1",
        kind=KnowledgeKind.POSITION,
        content="privileged plan content under Regulation R section 12",
        provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref="memo-plan"),
        valid_from=timestamp,
        ingested_at=timestamp,
        last_verified_at=timestamp,
        verified_by="Partner A",
        verified_state=VerifiedState.VERIFIED,
        credence_tier=CredenceTier.FIRM_AUTHORITATIVE,
    )
    indexed = service.index.upsert_item(item)
    service.store.write_item(indexed)
    service.graph.add_dependency(
        DependencyEdge(
            id="edge-1",
            source_id="item-1",
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
            valid_from=timestamp,
            created_at=timestamp,
        )
    )
    return service


def _read_plan() -> PrimitivePlanRequest:
    return PrimitivePlanRequest(
        steps=[
            PrimitivePlanStep(primitive="recall", args={"query": "Regulation R section 12", "limit": 5}),
            PrimitivePlanStep(primitive="evaluate_currency", args={"item_id": "item-1"}),
            PrimitivePlanStep(primitive="impact_query", args={"authority_id": "reg-r-12"}),
            PrimitivePlanStep(primitive="why", args={"item_id": "item-1"}),
        ]
    )
