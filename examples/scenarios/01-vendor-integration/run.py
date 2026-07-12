# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from solomon.api.service import AuthorityChangeRequest, DependencyRequest, IngestRequest, SolomonService
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.models import EdgeType
from solomon.mcp.tools.runtime import SolomonMCPRuntime

VENDOR_NAME = "VellumRelay"
AUTHORITY_ID = "reg-r-12"
AUTHORITY_CHANGE_DATE = "2025-01-01"


def _mock_llm_draft(current_context: list[dict[str, Any]]) -> str:
    if not current_context:
        return "No current firm position was injected; ask a lawyer to re-verify before drafting."
    return f"Draft grounded only in current firm context: {current_context[0]['content']}"


def run_scenario(root: Path) -> dict[str, Any]:
    service = SolomonService(data_dir=root / "data", journal_dir=root / "journal")
    runtime = SolomonMCPRuntime(service)
    memo = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.HOUSE_VIEW,
            content="Firm view: Structure X may rely on Regulation R section 12.",
            source_kind=SourceKind.PARTNER,
            source_ref="partner-memo-2023",
            author="Partner A",
            matter_id="matter-x",
            client_id="client-x",
        )
    )
    service.add_dependency(
        DependencyRequest(
            source_id=memo.id,
            target_id=AUTHORITY_ID,
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )
    initial_preflight = runtime.preflight_context(
        query="Structure X Regulation R section 12",
        matter_id="matter-x",
        client_id="client-x",
    )
    if len(initial_preflight["items"]) != 1:
        raise RuntimeError("expected one current item before the authority change")

    service.register_authority_change(
        AUTHORITY_ID,
        AuthorityChangeRequest(new_version="2025-amendment", changed_at=f"{AUTHORITY_CHANGE_DATE}T00:00:00+00:00"),
    )
    current_preflight = runtime.preflight_context(
        query="Structure X Regulation R section 12",
        matter_id="matter-x",
        client_id="client-x",
    )
    currency = runtime.check_currency(
        knowledge_item_id=memo.id,
        matter_id="matter-x",
        client_id="client-x",
    )
    current_context = current_preflight["items"]
    if current_context:
        raise RuntimeError("stale context must not be injected into the mock LLM")
    if currency["state"] != "stale_pending":
        raise RuntimeError("expected stale-pending-reverification after authority change")

    stale_message = (
        "The firm's prior view on Structure X depends on Regulation R section 12, "
        f"which moved on {AUTHORITY_CHANGE_DATE}; re-verification is required before reuse."
    )
    return {
        "vendor": VENDOR_NAME,
        "authority_change": {"authority_id": AUTHORITY_ID, "changed_on": AUTHORITY_CHANGE_DATE},
        "without_solomon": {
            "draft": f"Confident draft reusing stale text: {memo.content}",
            "reused_stale_text": True,
        },
        "with_solomon": {
            "initial_preflight": initial_preflight,
            "preflight_after_change": current_preflight,
            "currency": currency,
            "injected_context": current_context,
            "assistant_message": stale_message,
            "draft": _mock_llm_draft(current_context),
            "reused_stale_text": False,
        },
        "audit_ok": service.audit.verify().ok,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="solomon-vendor-integration-") as tmp:
        print(json.dumps(run_scenario(Path(tmp)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
