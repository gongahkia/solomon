# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from solomon.api.service import DependencyRequest, IngestRequest, SolomonService
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.models import EdgeType
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

    preflight = runtime.preflight_context(query="structure x", matter_id="matter-a", client_id="client-a")
    assert preflight["items"][0]["item"]["id"] in {item.id, successor.id}

    currency = runtime.check_currency(knowledge_item_id=item.id)
    assert currency["knowledge_item_id"] == item.id
    assert currency["state"] == "live"

    dependencies = runtime.get_dependencies(knowledge_item_id=item.id)
    assert dependencies["upstream"][0]["target_id"] == "reg-r-12"

    suggestions = runtime.dependency_suggestions(knowledge_item_id=item.id)
    assert "suggestions" in suggestions

    impact = runtime.impact(external_authority_id="reg-r-12")
    assert item.id in impact["stale_item_ids"]

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
