# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp
from uvicorn import Config, Server

from solomon import __version__
from solomon.api.schemas import SolomonModel
from solomon.api.service import SolomonService
from solomon.config import credence_policy_from_settings, get_settings, verification_policy_from_settings
from solomon.mcp.auth import MCPAuthConfig, bearer_token_matches, token_from_env
from solomon.mcp.tools import MCPToolSpec, SolomonMCPRuntime, mcp_tool_specs, register_solomon_tools
from solomon.mcp.transport import MCPShutdownConfig, MCPTransportConfig, MCPTransportKind


class SolomonMCPServerConfig(SolomonModel):
    name: str = "solomon"
    version: str
    transport: MCPTransportConfig = Field(default_factory=MCPTransportConfig)
    auth: MCPAuthConfig = Field(default_factory=MCPAuthConfig)
    tools: list[MCPToolSpec]


class MCPBearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, expected_token: str) -> None:
        super().__init__(app)
        self.expected_token = expected_token

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = _bearer_token_from_header(request.headers.get("authorization"))
        if not bearer_token_matches(supplied, self.expected_token):
            return JSONResponse(
                {"ok": False, "error": {"code": "scope_denied", "message": "missing or invalid bearer token"}},
                status_code=401,
            )
        return await call_next(request)


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
        sse_path="/sse",
        message_path="/messages/",
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
        verification_policy=verification_policy_from_settings(settings),
        verification_policy_version=settings.verification_policy_version,
        credence_policy=credence_policy_from_settings(settings),
        credence_policy_version=settings.credence_policy_version,
    )


def run_stdio_server(service: SolomonService | None = None) -> None:
    server = create_fastmcp_server(service or service_from_settings(), name="solomon", host="127.0.0.1")
    server.run("stdio")


def create_streamable_http_app(
    service: SolomonService,
    *,
    host: str = "127.0.0.1",
    port: int = 8141,
    expected_token: str | None = None,
) -> Starlette:
    return _with_bearer_auth(
        create_fastmcp_server(service, host=host, port=port).streamable_http_app(),
        expected_token=expected_token if expected_token is not None else token_from_env(),
    )


def create_sse_app(
    service: SolomonService,
    *,
    host: str = "127.0.0.1",
    port: int = 8141,
    expected_token: str | None = None,
) -> Starlette:
    return _with_bearer_auth(
        create_fastmcp_server(service, host=host, port=port).sse_app(),
        expected_token=expected_token if expected_token is not None else token_from_env(),
    )


def run_streamable_http_server(
    service: SolomonService | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8141,
) -> None:
    run_uvicorn_app(
        create_streamable_http_app(service or service_from_settings(), host=host, port=port),
        host=host,
        port=port,
    )


def run_sse_server(
    service: SolomonService | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8141,
) -> None:
    run_uvicorn_app(create_sse_app(service or service_from_settings(), host=host, port=port), host=host, port=port)


def default_server_config() -> SolomonMCPServerConfig:
    return create_server_config(version=__version__)


def uvicorn_config_for_app(
    app: ASGIApp,
    *,
    host: str,
    port: int,
    shutdown: MCPShutdownConfig | None = None,
) -> Config:
    resolved_shutdown = shutdown or MCPShutdownConfig.from_env()
    return Config(
        app,
        host=host,
        port=port,
        log_level="info",
        timeout_graceful_shutdown=resolved_shutdown.graceful_shutdown_seconds,
    )


def run_uvicorn_app(
    app: ASGIApp,
    *,
    host: str,
    port: int,
    shutdown: MCPShutdownConfig | None = None,
) -> None:
    Server(uvicorn_config_for_app(app, host=host, port=port, shutdown=shutdown)).run()


def main() -> None:
    run_stdio_server()


def _with_bearer_auth(app: Starlette, *, expected_token: str | None) -> Starlette:
    if expected_token is not None:
        app.add_middleware(MCPBearerAuthMiddleware, expected_token=expected_token)
    return app


def _bearer_token_from_header(value: str | None) -> str | None:
    if value is None:
        return None
    prefix = "Bearer "
    if not value.startswith(prefix):
        return None
    return value[len(prefix) :]


__all__ = [
    "MCPBearerAuthMiddleware",
    "SolomonMCPServerConfig",
    "available_tool_names",
    "create_fastmcp_server",
    "create_server_config",
    "create_sse_app",
    "create_streamable_http_app",
    "default_server_config",
    "main",
    "run_sse_server",
    "run_stdio_server",
    "run_streamable_http_server",
    "run_uvicorn_app",
    "service_from_settings",
    "uvicorn_config_for_app",
]


if __name__ == "__main__":
    main()
