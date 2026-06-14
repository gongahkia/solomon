# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from solomon.api.service import RecallRequest, SolomonService
from solomon.currency.models import CredenceTier, KnowledgeItem, KnowledgeKind, Provenance, SourceKind, VerifiedState
from solomon.currency.supersession import confirm_supersession, propose_supersession
from solomon.graph.store import supersedes_edge
from solomon.orchestrator.retrieval import RecallOptions


def _dt(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


def _position(item_id: str, content: str, *, year: int, metadata: dict[str, str]) -> KnowledgeItem:
    return KnowledgeItem(
        id=item_id,
        kind=KnowledgeKind.POSITION,
        content=content,
        provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref=item_id, author="Partner A"),
        valid_from=_dt(year),
        ingested_at=_dt(year),
        last_verified_at=_dt(2026),
        verified_by="Partner A",
        verified_state=VerifiedState.VERIFIED,
        credence_tier=CredenceTier.FIRM_AUTHORITATIVE,
        metadata=metadata,
    )


def warehouse_baseline(service: SolomonService, query: str) -> list[dict[str, Any]]:
    results = service.retrieval.recall(
        query,
        options=RecallOptions(review_mode=True, dedupe_near_identical=False),
    )[:2]
    return [
        {
            "item_id": result.item.id,
            "content": result.item.content,
            "supersession_signal": False,
        }
        for result in results
    ]


def run_scenario(root: Path) -> dict[str, Any]:
    service = SolomonService(data_dir=root / "data", journal_dir=root / "journal")
    old = _position(
        "position-2022",
        "2022 position: Structure Y may use the legacy notice route.",
        year=2022,
        metadata={"topic": "structure-y-notice-route", "jurisdiction": "SG"},
    )
    new = _position(
        "position-2024",
        "2024 position: Structure Y should not use the legacy notice route without partner review.",
        year=2024,
        metadata={
            "topic": "structure-y-notice-route",
            "jurisdiction": "SG",
            "contradicts": "position-2022",
        },
    )
    indexed_old = service.index.upsert_item(old)
    indexed_new = service.index.upsert_item(new)
    service.store.write_item(indexed_old)
    service.store.write_item(indexed_new)

    proposals = propose_supersession(indexed_new, [indexed_old])
    if not proposals:
        raise RuntimeError("expected supersession proposal")
    superseded, successor = confirm_supersession(service.store, proposals[0])
    service.graph.add_dependency(supersedes_edge(successor.id, superseded.id, created_by="Partner A"))

    default_recall = service.recall(RecallRequest(query="Structure Y legacy notice route"))
    review_recall = service.recall(
        RecallRequest(
            query="Structure Y legacy notice route",
            review_mode=True,
            limit=5,
        )
    )
    baseline = warehouse_baseline(service, "Structure Y legacy notice route")

    return {
        "proposal": proposals[0].model_dump(mode="json"),
        "superseded": {
            "item_id": superseded.id,
            "currency_state": superseded.currency_state.value,
            "successor_id": superseded.successor_id,
        },
        "successor": {
            "item_id": successor.id,
            "currency_state": successor.currency_state.value,
            "supersedes": successor.metadata.get("supersedes"),
        },
        "default_recall": default_recall,
        "review_recall": review_recall,
        "warehouse_baseline": baseline,
        "why_old": service.why(superseded.id).model_dump(mode="json"),
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="solomon-internal-supersession-") as tmp:
        result = run_scenario(Path(tmp))
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
