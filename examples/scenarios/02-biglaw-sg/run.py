# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

import httpx
import yaml  # type: ignore[import-untyped]

from solomon.api.service import AuthorityChangeRequest, DependencyRequest, IngestRequest, SolomonService
from solomon.console.app import create_console_app
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.models import EdgeType

SEED_PATH = Path(__file__).parent / "seed" / "seed.yaml"
MAS_NOTICE_626 = "MAS Notice 626"


def _seed() -> dict[str, Any]:
    loaded = yaml.safe_load(SEED_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RuntimeError("scenario seed must be a mapping")
    return loaded


def _seed_scenario(root: Path) -> tuple[dict[str, Any], SolomonService, list[str], Any]:
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
    return seed, service, dependent_ids, impact


def run_scenario(root: Path) -> dict[str, Any]:
    seed, service, dependent_ids, impact = _seed_scenario(root)
    states = [service.evaluate_currency(item_id)["currency_state"] for item_id in dependent_ids]
    return {
        "firm": seed["firm"],
        "seeded_internal_items": len(seed["items"]),
        "authority_anchors": list(seed["authorities"]),
        "authority_change": impact,
        "stale_dependent_count": len(dependent_ids),
        "states": states,
        "audit_ok": service.audit.verify().ok,
    }


def run_partner_console_walkthrough(root: Path) -> dict[str, Any]:
    seed, service, dependent_ids, _impact = _seed_scenario(root)
    successors = [
        service.ingest(
            IngestRequest(
                kind=KnowledgeKind.HOUSE_VIEW,
                content=f"Meridian Banyan LLP banking successor position {index + 1}.",
                source_kind=SourceKind.PARTNER,
                source_ref="banking-successor-review",
                matter_id="meridian-banyan-demo",
                client_id="fictional-client",
            )
        )
        for index in range(2)
    ]

    async def exercise() -> list[int]:
        transport = httpx.ASGITransport(app=create_console_app(service=service))
        statuses: list[int] = []
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            for item_id in dependent_ids[:3]:
                response = await client.post(
                    f"/console/verification/items/{item_id}/decision",
                    data={"decision": "reaffirm", "partner_id": "Partner Tan", "evidence_ref": "MAS review"},
                )
                statuses.append(response.status_code)
            for item_id, successor in zip(dependent_ids[3:5], successors, strict=True):
                response = await client.post(
                    f"/console/verification/items/{item_id}/decision",
                    data={
                        "decision": "supersede",
                        "partner_id": "Partner Tan",
                        "evidence_ref": "MAS review",
                        "successor_id": successor.id,
                    },
                )
                statuses.append(response.status_code)
            for item_id in dependent_ids[5:]:
                response = await client.post(
                    f"/console/verification/items/{item_id}/decision",
                    data={"decision": "retire", "partner_id": "Partner Tan", "evidence_ref": "MAS review"},
                )
                statuses.append(response.status_code)
        return statuses

    statuses = asyncio.run(exercise())
    if statuses != [200] * 7:
        raise RuntimeError(f"console walkthrough failed: {statuses}")
    states = [service.evaluate_currency(item_id)["currency_state"] for item_id in dependent_ids]
    expected = ["Live"] * 3 + ["Superseded"] * 2 + ["Retired"] * 2
    if states != expected:
        raise RuntimeError(f"unexpected post-review states: {states}")
    return {
        "firm": seed["firm"],
        "partner": "Partner Tan",
        "reaffirmed_count": 3,
        "superseded_count": 2,
        "retired_count": 2,
        "states": states,
        "audit_ok": service.audit.verify().ok,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Meridian Banyan Big Law scenario.")
    parser.add_argument("--console-walkthrough", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="solomon-biglaw-sg-") as tmp:
        runner = run_partner_console_walkthrough if args.console_walkthrough else run_scenario
        print(json.dumps(runner(Path(tmp)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
