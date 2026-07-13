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


def _seed() -> dict[str, Any]:
    loaded = yaml.safe_load(SEED_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RuntimeError("scenario seed must be a mapping")
    return loaded


def _seed_scenario(root: Path) -> tuple[dict[str, Any], SolomonService, dict[str, str], int, list[str], Any]:
    seed = _seed()
    memos = seed["memos"]
    authorities = seed["authority_anchors"]
    dependencies = seed["dependencies"]
    if not isinstance(memos, list) or len(memos) != 50:
        raise RuntimeError("expected 50 seeded memos")
    if not isinstance(authorities, list) or len(authorities) != 5:
        raise RuntimeError("expected five authority anchors")
    if not isinstance(dependencies, dict):
        raise RuntimeError("expected sparse dependency mapping")
    service = SolomonService(data_dir=root / "data", journal_dir=root / "journal")
    memo_ids: dict[str, str] = {}
    for memo in memos:
        if not isinstance(memo, str):
            raise RuntimeError("memo names must be strings")
        item = service.ingest(
            IngestRequest(
                kind=KnowledgeKind.HOUSE_VIEW,
                content=f"Kite & Quoin LLP working memo: {memo}.",
                source_kind=SourceKind.PARTNER,
                source_ref="boutique-psl-library",
                matter_id="kite-quoin-demo",
                client_id="fictional-client",
            )
        )
        memo_ids[memo] = item.id
    linked_memos = 0
    for authority, names in dependencies.items():
        if not isinstance(authority, str) or not isinstance(names, list):
            raise RuntimeError("dependencies must map authorities to memo lists")
        for memo in names:
            if not isinstance(memo, str) or memo not in memo_ids:
                raise RuntimeError("dependency references an unknown memo")
            service.add_dependency(
                DependencyRequest(
                    source_id=memo_ids[memo],
                    target_id=authority,
                    target_kind="external_authority",
                    edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
                )
            )
            linked_memos += 1
    impact = service.register_authority_change(
        "Personal Data Protection Act 2012",
        AuthorityChangeRequest(new_version="fictional-amendment-2026", changed_at="2026-01-15T00:00:00+00:00"),
    )
    stale_memos = dependencies["Personal Data Protection Act 2012"]
    if not isinstance(stale_memos, list):
        raise RuntimeError("expected privacy dependency list")
    states = [service.evaluate_currency(memo_ids[str(memo)])["currency_state"] for memo in stale_memos]
    if states != ["StalePendingReverification"] * 4:
        raise RuntimeError("privacy authority change must stale four linked memos")
    return seed, service, memo_ids, linked_memos, [str(memo) for memo in stale_memos], impact


def run_scenario(root: Path) -> dict[str, Any]:
    seed, service, memo_ids, linked_memos, stale_memos, impact = _seed_scenario(root)
    return {
        "firm": seed["firm"],
        "lawyer_count": seed["lawyer_count"],
        "seeded_memos": len(memo_ids),
        "authority_anchors": seed["authority_anchors"],
        "linked_memos": linked_memos,
        "authority_change": impact,
        "stale_memos": stale_memos,
        "audit_ok": service.audit.verify().ok,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="solomon-boutique-sg-") as tmp:
        print(json.dumps(run_scenario(Path(tmp)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
