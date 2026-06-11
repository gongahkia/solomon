# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from solomon.api.service import AuthorityChangeRequest, IngestRequest, RecallRequest, SolomonService
from solomon.audit.journal import what_did_we_know_report
from solomon.boundary.kaypoh import KaypohBoundary
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.models import DependencyEdge, EdgeType
from solomon.orchestrator.retrieval import RecallOptions


class DemoKaypohClient:
    def __init__(self) -> None:
        self.model_saw_text: str | None = None

    def review(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"classification": "SAFE", "findings": [], "request_id": "demo-review"}

    def pseudonymize(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        text = str(kwargs["request"]["text"])
        sanitized = text.replace("Client A", "[CLIENT_1]")
        self.model_saw_text = sanitized
        return {
            "pseudonymized_text": sanitized,
            "mapping": [{"placeholder": "[CLIENT_1]", "original_text": "Client A"}],
            "document_hash": "b" * 64,
        }

    def reidentify(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        text = str(kwargs["anonymized_text"]).replace("[CLIENT_1]", "Client A")
        return {"reidentified_text": text, "replacement_count": 1}

    def scrub_document(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"document_base64": kwargs["document_base64"], "metadata_findings": []}


def warehouse_baseline(service: SolomonService, query: str) -> list[dict[str, Any]]:
    results = service.retrieval.recall(
        query,
        options=RecallOptions(review_mode=True, dedupe_near_identical=False),
    )[0:1]
    return [
        {
            "item_id": result.item.id,
            "score": result.score,
            "content": result.item.content,
            "staleness_signal": False,
        }
        for result in results
    ]


def run_scenario(root: Path) -> dict[str, Any]:
    service = SolomonService(data_dir=root / "data", journal_dir=root / "journal")
    boundary_client = DemoKaypohClient()
    boundary = KaypohBoundary(boundary_client)

    memo = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.HOUSE_VIEW,
            content="2023 house view: structure X is compliant under Regulation R section 12 for Client A.",
            source_kind=SourceKind.PARTNER,
            source_ref="house-view-2023",
            author="Partner A",
            matter_id="client-a-2023",
            client_id="client-a",
        )
    )
    service.graph.add_dependency(
        DependencyEdge(
            source_id=memo.id,
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )
    impact = service.register_authority_change(
        "reg-r-12",
        request=AuthorityChangeRequest(new_version="2025-amendment", changed_at="2025-01-01T00:00:00+00:00"),
    )

    solomon_review = service.recall(RecallRequest(query="structure X Regulation R section 12", review_mode=True))
    baseline = warehouse_baseline(service, "structure X Regulation R")

    context = boundary.sanitize_context(
        "Question about Client A and structure X under Regulation R section 12.",
        matter_id="client-a-2023",
    )
    if "Client A" in context.sanitized_text:
        raise RuntimeError("sanitized context leaked client identity")
    if boundary_client.model_saw_text is None or "Client A" in boundary_client.model_saw_text:
        raise RuntimeError("model-facing text leaked client identity")

    audit_report = what_did_we_know_report(
        service.store.as_of(memo.ingested_at),
        as_of=memo.ingested_at,
        matter_id="client-a-2023",
    )

    return {
        "memo_id": memo.id,
        "impact": impact,
        "solomon_review": solomon_review,
        "warehouse_baseline_top": baseline,
        "model_saw_client_identity": "Client A" in (boundary_client.model_saw_text or ""),
        "audit_report": audit_report.model_dump(mode="json"),
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="solomon-stale-house-view-") as tmp:
        result = run_scenario(Path(tmp))
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
