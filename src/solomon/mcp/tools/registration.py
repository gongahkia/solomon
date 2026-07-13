# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from mcp.types import ToolAnnotations

from solomon.mcp.tools.helpers import structured_tool_errors
from solomon.mcp.tools.protocols import FastMCPProtocol
from solomon.mcp.tools.runtime import SolomonMCPRuntime
from solomon.mcp.tools.specs import READ_ONLY_TOOLS, TOOL_DESCRIPTIONS


def register_solomon_tools(server: FastMCPProtocol, runtime: SolomonMCPRuntime) -> None:
    def annotations_for(tool_name: str) -> ToolAnnotations:
        read_only = tool_name in READ_ONLY_TOOLS
        return ToolAnnotations(
            readOnlyHint=read_only,
            destructiveHint=not read_only,
            idempotentHint=read_only,
            openWorldHint=False,
        )

    server.tool(
        name="solomon.health",
        description=TOOL_DESCRIPTIONS["solomon.health"],
        annotations=annotations_for("solomon.health"),
        structured_output=True,
    )(structured_tool_errors(runtime.health))
    server.tool(
        name="solomon.preflight_context",
        description=TOOL_DESCRIPTIONS["solomon.preflight_context"],
        annotations=annotations_for("solomon.preflight_context"),
        structured_output=True,
    )(structured_tool_errors(runtime.preflight_context))
    server.tool(
        name="solomon.check_currency",
        description=TOOL_DESCRIPTIONS["solomon.check_currency"],
        annotations=annotations_for("solomon.check_currency"),
        structured_output=True,
    )(structured_tool_errors(runtime.check_currency))
    server.tool(
        name="solomon.get_dependencies",
        description=TOOL_DESCRIPTIONS["solomon.get_dependencies"],
        annotations=annotations_for("solomon.get_dependencies"),
        structured_output=True,
    )(structured_tool_errors(runtime.get_dependencies))
    server.tool(
        name="solomon.verify_position",
        description=TOOL_DESCRIPTIONS["solomon.verify_position"],
        annotations=annotations_for("solomon.verify_position"),
        structured_output=True,
    )(structured_tool_errors(runtime.verify_position))
    server.tool(
        name="solomon.verification_queue",
        description=TOOL_DESCRIPTIONS["solomon.verification_queue"],
        annotations=annotations_for("solomon.verification_queue"),
        structured_output=True,
    )(structured_tool_errors(runtime.verification_queue))
    server.tool(
        name="solomon.ingest",
        description=TOOL_DESCRIPTIONS["solomon.ingest"],
        annotations=annotations_for("solomon.ingest"),
        structured_output=True,
    )(structured_tool_errors(runtime.ingest))
    server.tool(
        name="solomon.audit_pack",
        description=TOOL_DESCRIPTIONS["solomon.audit_pack"],
        annotations=annotations_for("solomon.audit_pack"),
        structured_output=True,
    )(structured_tool_errors(runtime.audit_pack))
    server.tool(
        name="solomon.currency_report",
        description=TOOL_DESCRIPTIONS["solomon.currency_report"],
        annotations=annotations_for("solomon.currency_report"),
        structured_output=True,
    )(structured_tool_errors(runtime.currency_report))
    server.tool(
        name="solomon.dependency_suggestions",
        description=TOOL_DESCRIPTIONS["solomon.dependency_suggestions"],
        annotations=annotations_for("solomon.dependency_suggestions"),
        structured_output=True,
    )(structured_tool_errors(runtime.dependency_suggestions))
    server.tool(
        name="solomon.impact",
        description=TOOL_DESCRIPTIONS["solomon.impact"],
        annotations=annotations_for("solomon.impact"),
        structured_output=True,
    )(structured_tool_errors(runtime.impact))
