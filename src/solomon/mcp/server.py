# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.mcp.auth import MCPAuthConfig
from solomon.mcp.tools import MCPToolSpec, mcp_tool_specs
from solomon.mcp.transport import MCPTransportConfig, MCPTransportKind


class SolomonMCPServerConfig(SolomonModel):
    name: str = "solomon"
    version: str
    transport: MCPTransportConfig = Field(default_factory=MCPTransportConfig)
    auth: MCPAuthConfig = Field(default_factory=MCPAuthConfig)
    tools: list[MCPToolSpec]


def create_server_config(
    *,
    version: str,
    transport_kind: MCPTransportKind = "stdio",
    host: str = "127.0.0.1",
    port: int = 8141,
) -> SolomonMCPServerConfig:
    return SolomonMCPServerConfig(
        version=version,
        transport=MCPTransportConfig(kind=transport_kind, host=host, port=port),
        tools=mcp_tool_specs(),
    )


def available_tool_names() -> list[str]:
    return [tool.name for tool in mcp_tool_specs()]


__all__ = ["SolomonMCPServerConfig", "available_tool_names", "create_server_config"]
