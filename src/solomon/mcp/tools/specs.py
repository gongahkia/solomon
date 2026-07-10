# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from solomon.api.schemas import SolomonModel
from solomon.mcp.schemas import MCP_TOOL_JSON_SCHEMAS, JsonSchema


class MCPToolSpec(SolomonModel):
    name: str
    description: str
    read_only: bool
    input_schema: JsonSchema
    output_schema: JsonSchema


TOOL_DESCRIPTIONS: dict[str, str] = {
    "solomon.health": "Return Solomon MCP health, version, store, journal, and boundary status.",
    "solomon.preflight_context": "Return current, scoped firm context safe to inject into a prompt.",
    "solomon.check_currency": "Check whether a knowledge item is live, stale-pending, superseded, or retired.",
    "solomon.get_dependencies": "Return upstream and downstream dependency edges for a knowledge item.",
    "solomon.verify_position": "Record a human verification decision with evidence.",
    "solomon.verification_queue": "List items needing verification, optionally scoped to reviewer or matter.",
    "solomon.ingest": "Boundary-check and ingest new firm knowledge.",
    "solomon.audit_pack": "Export provenance, dependency, verification, boundary, and hash-chain evidence.",
    "solomon.dependency_suggestions": "Return proposed dependency edges for human confirmation.",
    "solomon.impact": "Return internal items affected by a changed external authority.",
}

READ_ONLY_TOOLS = {
    "solomon.health",
    "solomon.preflight_context",
    "solomon.check_currency",
    "solomon.get_dependencies",
    "solomon.verification_queue",
    "solomon.audit_pack",
    "solomon.dependency_suggestions",
    "solomon.impact",
}


def mcp_tool_specs() -> list[MCPToolSpec]:
    return [
        MCPToolSpec(
            name=tool_name,
            description=TOOL_DESCRIPTIONS[tool_name],
            read_only=tool_name in READ_ONLY_TOOLS,
            input_schema=schemas["input"],
            output_schema=schemas["output"],
        )
        for tool_name, schemas in MCP_TOOL_JSON_SCHEMAS.items()
    ]
