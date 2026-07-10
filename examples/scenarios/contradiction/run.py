# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from solomon.api.service import DependencyRequest, IngestRequest, RecallRequest, SolomonService
from solomon.currency.contradiction import ConclusionPolarity
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.models import EdgeType


def warehouse_baseline(service: SolomonService) -> list[dict[str, Any]]:
    return [
        {
            "item_id": item.id,
            "content": item.content,
            "contradiction_signal": False,
        }
        for item in service.store.get_many()
    ]


def run_scenario(root: Path) -> dict[str, Any]:
    service = SolomonService(data_dir=root / "data", journal_dir=root / "journal")
    allow = _ingest_position(
        service,
        source_ref="memo-allow",
        content="Memo A: Structure X may rely on Regulation R section 12.",
        conclusion="Structure X may rely on Regulation R section 12.",
        polarity=ConclusionPolarity.AFFIRMATIVE,
    )
    deny = _ingest_position(
        service,
        source_ref="memo-deny",
        content="Memo B: Structure X may not rely on Regulation R section 12.",
        conclusion="Structure X may not rely on Regulation R section 12.",
        polarity=ConclusionPolarity.NEGATIVE,
    )
    _depends_on(service, allow.id)
    _depends_on(service, deny.id)
    review_recall = service.recall(RecallRequest(query="Structure X Regulation R", review_mode=True, limit=5))
    return {
        "solomon": {
            "allow": service.why(allow.id).model_dump(mode="json"),
            "deny": service.why(deny.id).model_dump(mode="json"),
            "review_recall": review_recall,
            "audit_ok": service.audit.verify().ok,
        },
        "warehouse_baseline": warehouse_baseline(service),
    }


def _ingest_position(
    service: SolomonService,
    *,
    source_ref: str,
    content: str,
    conclusion: str,
    polarity: ConclusionPolarity,
) -> Any:
    return service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content=content,
            source_kind=SourceKind.PARTNER,
            source_ref=source_ref,
            matter_id="matter-a",
            client_id="client-a",
            conclusion=conclusion,
            conclusion_polarity=polarity,
        )
    )


def _depends_on(service: SolomonService, item_id: str) -> None:
    service.add_dependency(
        DependencyRequest(
            source_id=item_id,
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="solomon-contradiction-") as tmp:
        print(json.dumps(run_scenario(Path(tmp)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
