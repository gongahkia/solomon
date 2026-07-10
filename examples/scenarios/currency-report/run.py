# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from solomon.api.service import AuthorityChangeRequest, DependencyRequest, IngestRequest, SolomonService
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.models import EdgeType


def _dt(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def run_scenario(root: Path) -> dict[str, Any]:
    service = SolomonService(data_dir=root / "data", journal_dir=root / "journal")
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
    service.add_dependency(
        DependencyRequest(
            source_id=memo.id,
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
            created_by="Partner A",
            reason="2023 house view cites Regulation R section 12",
        )
    )
    service.register_authority_change(
        "reg-r-12",
        AuthorityChangeRequest(new_version="2025-amendment", changed_at="2025-01-01T00:00:00+00:00"),
    )
    report = service.currency_report(
        period_start=_dt(2025, 1, 1),
        period_end=_dt(2025, 12, 31),
        scope="matter",
        matter_id="client-a-2023",
        client_id="client-a",
    )
    return {
        "headline": f"here are the {len(report.items)} firm positions that went stale this period and why",
        "report": report.model_dump(mode="json"),
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="solomon-currency-report-") as tmp:
        print(json.dumps(run_scenario(Path(tmp)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
