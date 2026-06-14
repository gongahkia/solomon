# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from solomon import __version__
from solomon.api.schemas import SolomonModel
from solomon.api.service import SolomonService
from solomon.config import get_settings
from solomon.mcp.auth import MCPAuthConfig
from solomon.mcp.tools import MCPToolSpec, SolomonMCPRuntime, mcp_tool_specs, register_solomon_tools
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


def create_fastmcp_server(
    service: SolomonService,
    *,
    name: str = "solomon",
    host: str = "127.0.0.1",
    port: int = 8141,
) -> FastMCP:
    server = FastMCP(
        name,
        instructions="Solomon exposes current, scoped, boundary-aware internal legal knowledge tools.",
        host=host,
        port=port,
        streamable_http_path="/mcp",
    )
    register_solomon_tools(server, SolomonMCPRuntime(service))
    return server


def service_from_settings() -> SolomonService:
    settings = get_settings()
    return SolomonService(
        data_dir=settings.data_dir,
        journal_dir=settings.journal_dir,
        attestation_key=settings.verification_attestation_key,
        database_url=settings.database_url,
    )


def run_stdio_server(service: SolomonService | None = None) -> None:
    server = create_fastmcp_server(service or service_from_settings(), name="solomon", host="127.0.0.1")
    server.run("stdio")


def default_server_config() -> SolomonMCPServerConfig:
    return create_server_config(version=__version__)


def main() -> None:
    run_stdio_server()


__all__ = [
    "SolomonMCPServerConfig",
    "available_tool_names",
    "create_fastmcp_server",
    "create_server_config",
    "default_server_config",
    "main",
    "run_stdio_server",
    "service_from_settings",
]


if __name__ == "__main__":
    main()
