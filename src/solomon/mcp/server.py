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
from solomon.boundary.solomon import SolomonBoundary
from solomon.config import (
    boundary_policy_from_settings,
    credence_policy_from_settings,
    get_settings,
    verification_policy_from_settings,
)
from solomon.mcp.auth import MCPAuthConfig, bearer_token_matches, token_from_env
from solomon.mcp.tools import MCPToolSpec, SolomonMCPRuntime, mcp_tool_specs, register_solomon_tools
from solomon.mcp.tools.helpers import _error_result
from solomon.mcp.transport import MCPShutdownConfig, MCPTransportConfig, MCPTransportKind

PROTECTED_RESOURCE_METADATA_PREFIX = "/.well-known/oauth-protected-resource"


class SolomonMCPServerConfig(SolomonModel):
    name: str = "solomon"
    version: str
    transport: MCPTransportConfig = Field(default_factory=MCPTransportConfig)
    auth: MCPAuthConfig = Field(default_factory=MCPAuthConfig)
    tools: list[MCPToolSpec]


class MCPBearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, expected_token: str, metadata_path: str) -> None:
        super().__init__(app)
        self.expected_token = expected_token
        self.metadata_path = metadata_path

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method == "GET" and request.url.path == self.metadata_path:
            return await call_next(request)
        supplied = _bearer_token_from_header(request.headers.get("authorization"))
        if not bearer_token_matches(supplied, self.expected_token):
            metadata_url = _request_url(request, self.metadata_path)
            return JSONResponse(
                _error_result(
                    "scope_denied",
                    "missing or invalid bearer token",
                    retryable=False,
                    details={},
                ),
                status_code=401,
                headers={"WWW-Authenticate": f'Bearer resource_metadata="{metadata_url}"'},
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
        boundary=SolomonBoundary(policy=boundary_policy_from_settings(settings)),
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
    auth: MCPAuthConfig | None = None,
) -> Starlette:
    return _with_bearer_auth(
        create_fastmcp_server(service, host=host, port=port).streamable_http_app(),
        expected_token=expected_token if expected_token is not None else token_from_env(),
        auth=auth or MCPAuthConfig(),
        resource_path="/mcp",
    )


def create_sse_app(
    service: SolomonService,
    *,
    host: str = "127.0.0.1",
    port: int = 8141,
    expected_token: str | None = None,
    auth: MCPAuthConfig | None = None,
) -> Starlette:
    return _with_bearer_auth(
        create_fastmcp_server(service, host=host, port=port).sse_app(),
        expected_token=expected_token if expected_token is not None else token_from_env(),
        auth=auth or MCPAuthConfig(),
        resource_path="/sse",
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


def _with_bearer_auth(
    app: Starlette,
    *,
    expected_token: str | None,
    auth: MCPAuthConfig,
    resource_path: str,
) -> Starlette:
    metadata_path = f"{PROTECTED_RESOURCE_METADATA_PREFIX}{resource_path}"

    async def protected_resource_metadata(request: Request) -> JSONResponse:
        payload: dict[str, object] = {
            "resource": _request_url(request, resource_path),
            "bearer_methods_supported": ["header"],
            "resource_name": auth.resource_name,
        }
        if auth.authorization_servers:
            payload["authorization_servers"] = list(auth.authorization_servers)
        if auth.scopes:
            payload["scopes_supported"] = list(auth.scopes)
        return JSONResponse(payload)

    app.add_route(metadata_path, protected_resource_metadata, methods=["GET"])
    if expected_token is not None:
        app.add_middleware(MCPBearerAuthMiddleware, expected_token=expected_token, metadata_path=metadata_path)
    return app


def _request_url(request: Request, path: str) -> str:
    return str(request.url.replace(path=path, query=None))


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
