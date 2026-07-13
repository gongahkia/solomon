# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from solomon.api.service import SolomonService
from solomon.api.service_models import DependencyRequest, IngestRequest
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.models import EdgeType
from solomon.mcp.tools.runtime import SolomonMCPRuntime


def test_mcp_dependency_depth_traverses_and_reports_truncation(tmp_path):
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    root = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.NOTE,
            content="Root note relies on the prior note.",
            source_kind=SourceKind.ASSOCIATE,
            source_ref="root",
            matter_id="matter-a",
            client_id="client-a",
        )
    )
    middle = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.NOTE,
            content="Prior note relies on Regulation R section 12.",
            source_kind=SourceKind.ASSOCIATE,
            source_ref="middle",
            matter_id="matter-a",
            client_id="client-a",
        )
    )
    service.add_dependency(
        DependencyRequest(
            source_id=root.id,
            target_id=middle.id,
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_INTERNAL,
            target_kind="knowledge_item",
        )
    )
    service.add_dependency(
        DependencyRequest(
            source_id=middle.id,
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )
    runtime = SolomonMCPRuntime(service)

    shallow = runtime.get_dependencies(knowledge_item_id=root.id, depth=1)
    deep = runtime.get_dependencies(knowledge_item_id=root.id, depth=2)
    invalid = runtime.get_dependencies(knowledge_item_id=root.id, depth=0)

    assert [edge["target_id"] for edge in shallow["upstream"]] == [middle.id]
    assert shallow["truncated"] is True
    assert [edge["target_id"] for edge in deep["upstream"]] == [middle.id, "reg-r-12"]
    assert deep["truncated"] is False
    assert invalid["error"]["code"] == "invalid_request"
