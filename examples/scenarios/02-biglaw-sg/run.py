# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from solomon.api.service import AuthorityChangeRequest, DependencyRequest, IngestRequest, SolomonService
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.models import EdgeType

SEED_PATH = Path(__file__).parent / "seed" / "seed.yaml"
MAS_NOTICE_626 = "MAS Notice 626"


def _seed() -> dict[str, Any]:
    loaded = yaml.safe_load(SEED_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RuntimeError("scenario seed must be a mapping")
    return loaded


def run_scenario(root: Path) -> dict[str, Any]:
    seed = _seed()
    items = seed["items"]
    if not isinstance(items, list) or len(items) != 30:
        raise RuntimeError("expected 30 seeded internal items")
    if not isinstance(seed["authorities"], list) or len(seed["authorities"]) != 8:
        raise RuntimeError("expected 8 authority anchors")
    service = SolomonService(data_dir=root / "data", journal_dir=root / "journal")
    seeded: list[tuple[str, str]] = []
    for entry in items:
        practice = str(entry["practice"])
        title = str(entry["title"])
        item = service.ingest(
            IngestRequest(
                kind=KnowledgeKind.HOUSE_VIEW,
                content=f"Meridian Banyan LLP {practice} position: {title}.",
                source_kind=SourceKind.PARTNER,
                source_ref=f"{practice}-playbook",
                matter_id="meridian-banyan-demo",
                client_id="fictional-client",
            )
        )
        seeded.append((title, item.id))
    dependent_ids = [item_id for _title, item_id in seeded if "MAS Notice 626" in _title]
    if len(dependent_ids) != 7:
        raise RuntimeError("expected seven MAS Notice 626 dependent memos")
    for item_id in dependent_ids:
        service.add_dependency(
            DependencyRequest(
                source_id=item_id,
                target_id=MAS_NOTICE_626,
                target_kind="external_authority",
                edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            )
        )
    impact = service.register_authority_change(
        MAS_NOTICE_626,
        AuthorityChangeRequest(new_version="fictional-amendment-2026", changed_at="2026-01-15T00:00:00+00:00"),
    )
    states = [service.evaluate_currency(item_id)["currency_state"] for item_id in dependent_ids]
    if states != ["StalePendingReverification"] * 7:
        raise RuntimeError("MAS Notice 626 change must stale all seven dependent memos")
    return {
        "firm": seed["firm"],
        "seeded_internal_items": len(seeded),
        "authority_anchors": list(seed["authorities"]),
        "authority_change": impact,
        "stale_dependent_count": len(dependent_ids),
        "states": states,
        "audit_ok": service.audit.verify().ok,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="solomon-biglaw-sg-") as tmp:
        print(json.dumps(run_scenario(Path(tmp)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
