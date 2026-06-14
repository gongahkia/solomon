# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from solomon.api.service import DependencyRequest, IngestRequest, SolomonService
from solomon.boundary.solomon import SolomonBoundary
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.models import EdgeType
from solomon.mcp.rate_limit import TokenBucketConfig, TokenBucketRateLimiter
from solomon.mcp.tools import SolomonMCPRuntime


def test_mcp_runtime_maps_all_required_tools_to_service(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    runtime = SolomonMCPRuntime(service)

    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x depends on regulation r section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-1",
            matter_id="matter-a",
            client_id="client-a",
        )
    )
    successor = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="updated structure x view",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-2",
            matter_id="matter-a",
            client_id="client-a",
        )
    )
    service.add_dependency(
        DependencyRequest(
            source_id=item.id,
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )
    other_item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="other matter also depends on regulation r section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-other",
            matter_id="matter-b",
            client_id="client-b",
        )
    )
    service.add_dependency(
        DependencyRequest(
            source_id=other_item.id,
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )

    preflight = runtime.preflight_context(query="structure x", matter_id="matter-a", client_id="client-a")
    assert preflight["items"][0]["item"]["id"] in {item.id, successor.id}

    currency = runtime.check_currency(knowledge_item_id=item.id)
    assert currency["knowledge_item_id"] == item.id
    assert currency["state"] == "live"

    denied = runtime.check_currency(knowledge_item_id=item.id, matter_id="matter-b", client_id="client-b")
    assert denied["ok"] is False
    assert denied["error"]["code"] == "scope_denied"

    dependencies = runtime.get_dependencies(knowledge_item_id=item.id)
    assert dependencies["upstream"][0]["target_id"] == "reg-r-12"

    suggestions = runtime.dependency_suggestions(knowledge_item_id=item.id)
    assert "suggestions" in suggestions

    impact = runtime.impact(external_authority_id="reg-r-12", matter_id="matter-a", client_id="client-a")
    assert item.id in impact["stale_item_ids"]
    assert other_item.id not in impact["stale_item_ids"]

    verification = runtime.verify_position(
        knowledge_item_id=item.id,
        verifier_id="partner-a",
        decision="supersede",
        evidence_ref="memo-2",
        successor_id=successor.id,
    )
    assert verification["item"]["successor_id"] == successor.id
    assert verification["currency"]["state"] == "superseded"

    ingested = runtime.ingest(
        text="new clause depends on regulation r section 12",
        source_ref="memo-3",
        scope={"matter_id": "matter-a", "client_id": "client-a"},
        kind="clause",
        source_kind="associate",
    )
    assert ingested["item"]["kind"] == "clause"

    audit_pack = runtime.audit_pack(knowledge_item_id=item.id)
    assert audit_pack["knowledge_item_id"] == item.id
    assert audit_pack["format"] == "json"
    assert "manifest_json" in audit_pack["pack"]


def test_mcp_preflight_rejects_boundary_unsafe_output(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x under regulation r section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-1",
        )
    )
    service.boundary = SolomonBoundary(HighRiskBoundaryClient())
    runtime = SolomonMCPRuntime(service)

    result = runtime.preflight_context(query=item.content)

    assert result["ok"] is False
    assert result["error"]["code"] == "boundary_rejected"
    assert result["error"]["details"]["classification"] == "HIGH_RISK"


def test_mcp_call_logging_records_required_fields(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x under regulation r section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-1",
            matter_id="matter-a",
            client_id="client-a",
        )
    )
    runtime = SolomonMCPRuntime(service)

    runtime.check_currency(
        knowledge_item_id=item.id,
        matter_id="matter-a",
        client_id="client-a",
        caller_id="claude:test",
    )

    entries = [
        json.loads(line)
        for line in (tmp_path / "journal" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    mcp_entries = [entry for entry in entries if entry["event_type"] == "mcp_call"]
    payload = mcp_entries[-1]["payload"]
    assert payload["tool_name"] == "solomon.check_currency"
    assert payload["caller_id"] == "claude:test"
    assert payload["matter_id"] == "matter-a"
    assert payload["client_id"] == "client-a"
    assert payload["currency_outcome"] == "live"
    assert payload["boundary_outcome"] is None
    assert payload["input_sha256"]


def test_mcp_runtime_rate_limits_per_caller(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x under regulation r section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-1",
        )
    )
    limiter = TokenBucketRateLimiter(TokenBucketConfig(capacity=1, refill_per_second=0.0))
    runtime = SolomonMCPRuntime(service, rate_limiter=limiter)

    first = runtime.check_currency(knowledge_item_id=item.id, caller_id="caller-a")
    second = runtime.check_currency(knowledge_item_id=item.id, caller_id="caller-a")
    other = runtime.check_currency(knowledge_item_id=item.id, caller_id="caller-b")

    assert first["state"] == "live"
    assert second["ok"] is False
    assert second["error"]["code"] == "rate_limited"
    assert other["state"] == "live"


class HighRiskBoundaryClient:
    def review(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"classification": "HIGH_RISK", "findings": [{"kind": "mnpi_or_high_risk_secret"}]}

    def pseudonymize(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"pseudonymized_text": "", "mapping": []}

    def reidentify(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"reidentified_text": ""}

    def scrub_document(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}
