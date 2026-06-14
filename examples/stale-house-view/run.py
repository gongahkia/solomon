# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from solomon.api.service import AuthorityChangeRequest, IngestRequest, RecallRequest, SolomonService
from solomon.audit.journal import what_did_we_know_report
from solomon.boundary.solomon import SolomonBoundary
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.models import DependencyEdge, EdgeType
from solomon.orchestrator.retrieval import RecallOptions


def _dt(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


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
    boundary = SolomonBoundary()
    service = SolomonService(data_dir=root / "data", journal_dir=root / "journal", boundary=boundary)

    memo = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.HOUSE_VIEW,
            content="2023 house view: structure X is compliant under Regulation R section 12 for Client A.",
            source_kind=SourceKind.PARTNER,
            source_ref="house-view-2023",
            author="Partner A",
            matter_id="client-a-2023",
            client_id="client-a",
            valid_from=_dt(2023, 1, 1),
            ingested_at=_dt(2023, 1, 2),
        )
    )
    service.graph.add_dependency(
        DependencyEdge(
            source_id=memo.id,
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
            valid_from=_dt(2023, 1, 2),
            created_at=_dt(2023, 1, 2),
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
    model_saw_text = context.sanitized_text

    audit_report = what_did_we_know_report(
        service.store.as_of(_dt(2026, 1, 1)),
        as_of=_dt(2026, 1, 1),
        matter_id="client-a-2023",
    )
    stale_reasons = service.store.get_item(memo.id).metadata.get("staleness_reasons", [])
    verification_prompt = (
        "Re-verify before reuse: Regulation R section 12 changed in 2025 and this house view has not "
        "been reaffirmed after the change."
    )

    return {
        "memo_id": memo.id,
        "impact": impact,
        "solomon_review": solomon_review,
        "warehouse_baseline_top": baseline,
        "model_saw_client_identity": "Client A" in model_saw_text,
        "model_saw_text": model_saw_text,
        "audit_report": audit_report.model_dump(mode="json"),
        "audit_chain": {
            "known_since": memo.ingested_at.isoformat(),
            "dependency": "reg-r-12",
            "dependency_change": impact["reasons"][memo.id][0],
            "stale_flag": stale_reasons[0] if stale_reasons else None,
            "verification_prompt": verification_prompt,
        },
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="solomon-stale-house-view-") as tmp:
        result = run_scenario(Path(tmp))
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
