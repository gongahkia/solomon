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
from solomon.mcp.tools.runtime import SolomonMCPRuntime

SEED_PATH = Path(__file__).parent / "seed" / "seed.yaml"


def _seed() -> dict[str, Any]:
    loaded = yaml.safe_load(SEED_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RuntimeError("scenario seed must be a mapping")
    return loaded


def _copilot_suggestion(current_context: list[dict[str, Any]]) -> str:
    if not current_context:
        return "No current NDA language is available; route the request to Legal for re-verification."
    return f"Suggested language grounded in current context: {current_context[0]['content']}"


def run_scenario(root: Path) -> dict[str, Any]:
    seed = _seed()
    authority = str(seed["authority"])
    items = seed["items"]
    if not isinstance(items, list):
        raise RuntimeError("scenario seed items must be a list")
    service = SolomonService(data_dir=root / "data", journal_dir=root / "journal")
    runtime = SolomonMCPRuntime(service)
    nda_ids: list[str] = []
    for entry in items:
        kind = str(entry["kind"])
        title = str(entry["title"])
        item = service.ingest(
            IngestRequest(
                kind=KnowledgeKind.HOUSE_VIEW,
                content=f"Lantern Circuit internal {kind}: {title}; prior transfer clause cites {authority}.",
                source_kind=SourceKind.ASSOCIATE,
                source_ref=f"{kind}-library",
                matter_id="lantern-circuit-demo",
                client_id="lantern-circuit",
            )
        )
        if kind == "nda":
            nda_ids.append(item.id)
            service.add_dependency(
                DependencyRequest(
                    source_id=item.id,
                    target_id=authority,
                    target_kind="external_authority",
                    edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
                )
            )
    if len(nda_ids) != 12:
        raise RuntimeError("expected 12 NDA clauses")
    before = runtime.preflight_context(
        query="NDA",
        matter_id="lantern-circuit-demo",
        client_id="lantern-circuit",
    )
    service.register_authority_change(
        authority,
        AuthorityChangeRequest(new_version="fictional-pdpa-amendment", changed_at="2026-02-01T00:00:00+00:00"),
    )
    after = runtime.preflight_context(
        query="NDA",
        matter_id="lantern-circuit-demo",
        client_id="lantern-circuit",
    )
    states = [service.evaluate_currency(item_id)["currency_state"] for item_id in nda_ids]
    if states != ["StalePendingReverification"] * 12:
        raise RuntimeError("PDPA change must stale all twelve NDA clauses")
    if after["items"]:
        raise RuntimeError("Copilot-like assistant must not receive stale NDA context")
    return {
        "company": seed["company"],
        "nda_count": len(nda_ids),
        "preflight_before": before,
        "preflight_after": after,
        "states": states,
        "copilot_suggestion": _copilot_suggestion(after["items"]),
        "audit_ok": service.audit.verify().ok,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="solomon-inhouse-gc-") as tmp:
        print(json.dumps(run_scenario(Path(tmp)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
