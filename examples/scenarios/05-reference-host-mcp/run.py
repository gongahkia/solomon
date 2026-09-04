# SPDX-License-Identifier: Apache-2.0

"""Run a fictional legal-assistant host through Solomon's real MCP stdio transport.

This is an integration proof, not a compatibility claim for a named MCP host or a
test of an LLM.  The host policy is deliberately small: it invokes only two
read-only tools and never injects content unless preflight returned it.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from collections.abc import Awaitable
from pathlib import Path
from typing import Any, TypeVar

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from solomon.api.service import AuthorityChangeRequest, DependencyRequest, IngestRequest, SolomonService
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.models import EdgeType

HOST_ID = "reference-legal-host"
MATTER_ID = "matter-reference-host"
CLIENT_ID = "client-reference-host"
AUTHORITY_ID = "regulation-r-section-12"
AUTHORITY_CHANGE_DATE = "2026-01-01"
READ_ONLY_TOOL_ALLOWLIST = ("solomon.preflight_context", "solomon.check_currency")

_Value = TypeVar("_Value")


def run_scenario(root: Path) -> dict[str, Any]:
    """Exercise the pre-draft gate before and after a known authority change."""

    database_url = f"sqlite:///{root / 'data' / 'solomon.sqlite3'}"
    service = SolomonService(
        data_dir=root / "data",
        journal_dir=root / "journal",
        database_url=database_url,
    )
    position = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="Firm position: Structure X may rely on Regulation R section 12.",
            source_kind=SourceKind.PARTNER,
            source_ref="fictional-partner-memo-2025",
            author="Partner A",
            matter_id=MATTER_ID,
            client_id=CLIENT_ID,
        )
    )
    service.add_dependency(
        DependencyRequest(
            source_id=position.id,
            target_id=AUTHORITY_ID,
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )

    async def exercise() -> dict[str, Any]:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "solomon.mcp.server"],
            cwd=Path.cwd(),
            env={
                "SOLOMON_DATA_DIR": str(root / "data"),
                "SOLOMON_JOURNAL_DIR": str(root / "journal"),
                "SOLOMON_DATABASE_URL": database_url,
                "SOLOMON_MCP_REQUIRE_IDENTITY": "true",
                "SOLOMON_MCP_PRINCIPAL_JSON": json.dumps(
                    {
                        "subject": HOST_ID,
                        "role": "integration",
                        "scopes": ["solomon.read"],
                        "matter_ids": [MATTER_ID],
                        "client_ids": [CLIENT_ID],
                    }
                ),
            },
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                available_tools = {tool.name for tool in (await session.list_tools()).tools}
                _require(set(READ_ONLY_TOOL_ALLOWLIST) <= available_tools, "reference host tool availability")

                before = await _call(
                    session,
                    "solomon.preflight_context",
                    {
                        "query": "Structure X Regulation R section 12",
                        "matter_id": MATTER_ID,
                        "client_id": CLIENT_ID,
                        "max_items": 1,
                    },
                )
                before_decision = _host_decision(before, position.id)
                _require(before_decision["decision"] == "reuse_current_context", "live context is reusable")

                service.register_authority_change(
                    AUTHORITY_ID,
                    AuthorityChangeRequest(
                        new_version="fictional-amendment-2026",
                        changed_at=f"{AUTHORITY_CHANGE_DATE}T00:00:00+00:00",
                    ),
                )
                after = await _call(
                    session,
                    "solomon.preflight_context",
                    {
                        "query": "Structure X Regulation R section 12",
                        "matter_id": MATTER_ID,
                        "client_id": CLIENT_ID,
                        "max_items": 1,
                    },
                )
                currency = await _call(
                    session,
                    "solomon.check_currency",
                    {
                        "knowledge_item_id": position.id,
                        "matter_id": MATTER_ID,
                        "client_id": CLIENT_ID,
                    },
                )
                after_decision = _host_decision(after, position.id, currency=currency)
                _require(after_decision["decision"] == "require_human_reverification", "stale context is withheld")
                _require(currency["state"] == "stale_pending", "currency state after authority change")

                return {
                    "advertised_tools": sorted(available_tools),
                    "before": before_decision,
                    "after": after_decision,
                    "currency": currency,
                }

    transport_result = asyncio.run(exercise())
    audit_entries = [
        json.loads(line)
        for line in (root / "journal" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    mcp_entries = [entry for entry in audit_entries if entry.get("event_type") == "mcp_call"]
    _require(len(mcp_entries) == 3, "three read-only MCP calls were audited")
    _require(
        all(entry.get("attribution", {}).get("actor_id") == HOST_ID for entry in mcp_entries),
        "bound MCP identity attribution",
    )
    _require(service.audit.verify().ok, "audit chain verification")

    return {
        "scenario": "fictional-reference-host-mcp",
        "claims": {
            "named_host_compatibility": False,
            "model_or_legal_correctness": False,
            "transport": "MCP stdio",
        },
        "host_policy": {
            "principal": HOST_ID,
            "read_only_tool_allowlist": list(READ_ONLY_TOOL_ALLOWLIST),
            "inject_only_preflight_items": True,
            "fallback": "require_human_reverification",
        },
        "authority_change": {"authority_id": AUTHORITY_ID, "changed_on": AUTHORITY_CHANGE_DATE},
        "transport_proof": transport_result,
        "audit": {"verified": True, "mcp_call_count": len(mcp_entries)},
    }


async def _call(
    session: ClientSession,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    result = await _await(session.call_tool(tool_name, arguments))
    payload = result.structuredContent
    if not isinstance(payload, dict):
        raise RuntimeError(f"{tool_name} returned no structured MCP payload")
    if payload.get("ok") is False:
        raise RuntimeError(f"{tool_name} failed: {payload.get('error', {}).get('code', 'unknown')}")
    return payload


async def _await(awaitable: Awaitable[_Value]) -> _Value:
    return await awaitable


def _host_decision(
    preflight: dict[str, Any],
    expected_item_id: str,
    *,
    currency: dict[str, Any] | None = None,
) -> dict[str, Any]:
    items = preflight.get("items")
    if not isinstance(items, list):
        raise RuntimeError("preflight items must be a list")
    injected_item_ids = [
        item.get("item", {}).get("id")
        for item in items
        if isinstance(item, dict) and isinstance(item.get("item"), dict) and isinstance(item["item"].get("id"), str)
    ]
    if expected_item_id in injected_item_ids:
        return {
            "decision": "reuse_current_context",
            "injected_item_ids": injected_item_ids,
            "host_message": "Draft only from the current context returned by Solomon.",
        }
    if currency is None or currency.get("state") != "stale_pending":
        raise RuntimeError("an empty preflight result is not sufficient to infer a review decision")
    return {
        "decision": "require_human_reverification",
        "injected_item_ids": [],
        "host_message": (
            "The requested firm position is review-due because a recorded dependency changed; "
            "a human must re-verify it before reuse."
        ),
        "excluded_codes": sorted(
            exclusion["code"]
            for exclusion in preflight.get("excluded", [])
            if isinstance(exclusion, dict) and isinstance(exclusion.get("code"), str)
        ),
    }


def _require(condition: bool, description: str) -> None:
    if not condition:
        raise RuntimeError(f"reference host invariant failed: {description}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="solomon-reference-host-mcp-") as tmp:
        print(json.dumps(run_scenario(Path(tmp)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
