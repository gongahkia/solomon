# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from starlette.types import Message

from solomon import __version__
from solomon.api.service import IngestRequest, SolomonService
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.mcp.auth import MCPAuthConfig, bearer_token_matches, token_from_env
from solomon.mcp.logging import hash_mcp_input
from solomon.mcp.server import (
    available_tool_names,
    create_fastmcp_server,
    create_server_config,
    create_streamable_http_app,
    uvicorn_config_for_app,
)
from solomon.mcp.tools import READ_ONLY_TOOLS, mcp_tool_specs
from solomon.mcp.transport import MCPShutdownConfig, MCPTransportConfig


def test_mcp_server_config_exposes_all_schema_tools() -> None:
    config = create_server_config(version=__version__)

    assert config.name == "solomon"
    assert config.transport.kind == "stdio"
    assert len(config.tools) == len(available_tool_names())
    assert set(available_tool_names()) == {tool.name for tool in mcp_tool_specs()}


def test_mcp_tool_specs_mark_write_tools() -> None:
    specs = {tool.name: tool for tool in mcp_tool_specs()}

    assert specs["solomon.ingest"].read_only is False
    assert specs["solomon.verify_position"].read_only is False
    assert set(READ_ONLY_TOOLS).issubset(specs)
    assert specs["solomon.preflight_context"].input_schema["type"] == "object"


def test_mcp_transport_config_url_only_for_http() -> None:
    assert MCPTransportConfig(kind="stdio").url is None
    assert MCPTransportConfig(kind="streamable-http", host="localhost", port=9000).url == "http://localhost:9000/mcp"
    assert MCPTransportConfig(kind="sse", host="localhost", port=9000).url == "http://localhost:9000/sse"


def test_mcp_auth_reads_configured_env_and_compares_constant_time() -> None:
    config = MCPAuthConfig(credential_env_var="CUSTOM_TOKEN")

    assert token_from_env(config, {"CUSTOM_TOKEN": "secret"}) == "secret"
    assert bearer_token_matches("secret", "secret")
    assert not bearer_token_matches("wrong", "secret")
    assert not bearer_token_matches(None, "secret")
    assert bearer_token_matches(None, None)


def test_mcp_input_hash_is_stable_across_key_order() -> None:
    left = hash_mcp_input({"b": 2, "a": 1})
    right = hash_mcp_input({"a": 1, "b": 2})

    assert left == right


def test_fastmcp_server_registers_solomon_tools(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    server = create_fastmcp_server(service)

    async def check() -> None:
        tools = await server.list_tools()
        assert {tool.name for tool in tools} == set(available_tool_names())
        assert "solomon.preflight_context" in {tool.name for tool in tools}

    anyio.run(check)


def test_fastmcp_runtime_calls_service(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x under regulation r section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo",
        )
    )
    server = create_fastmcp_server(service)

    async def call() -> None:
        result = await server.call_tool(
            "solomon.check_currency",
            {"knowledge_item_id": item.id},
        )
        payload = _structured_payload(result)
        assert payload["knowledge_item_id"] == item.id
        assert payload["state"] == "live"

    anyio.run(call)


def test_fastmcp_tool_errors_use_stable_structured_envelopes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x under regulation r section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo",
            matter_id="matter-a",
            client_id="client-a",
        )
    )
    server = create_fastmcp_server(service)

    async def call() -> None:
        validation = _structured_payload(
            await server.call_tool(
                "solomon.verify_position",
                {
                    "knowledge_item_id": item.id,
                    "verifier_id": "lawyer-a",
                    "decision": "unknown",
                    "evidence_ref": "memo",
                },
            )
        )
        state = _structured_payload(await server.call_tool("solomon.check_currency", {"knowledge_item_id": "missing"}))
        authorization = _structured_payload(
            await server.call_tool(
                "solomon.check_currency",
                {"knowledge_item_id": item.id, "matter_id": "matter-b", "client_id": "client-b"},
            )
        )

        def fail_search(*args: object, **kwargs: object) -> object:
            raise ConnectionError("index unavailable")

        monkeypatch.setattr(service.index, "search", fail_search)
        upstream = _structured_payload(await server.call_tool("solomon.preflight_context", {"query": "structure"}))

        assert validation["error"] == {
            "category": "validation",
            "code": "validation_failed",
            "message": "MCP tool request failed validation",
            "retryable": False,
            "details": {},
        }
        assert state["error"]["category"] == "state"
        assert state["error"]["code"] == "state_not_found"
        assert authorization["error"]["category"] == "authorization"
        assert authorization["error"]["code"] == "scope_denied"
        assert upstream["error"] == {
            "category": "upstream",
            "code": "upstream_failure",
            "message": "MCP tool upstream dependency failed",
            "retryable": True,
            "details": {},
        }

    anyio.run(call)


def test_stdio_server_lists_tools(tmp_path: Path) -> None:
    async def call() -> None:
        params = StdioServerParameters(
            command="uv",
            args=["run", "python", "-m", "solomon.mcp.server"],
            cwd=Path.cwd(),
            env={
                "SOLOMON_DATA_DIR": str(tmp_path / "data"),
                "SOLOMON_JOURNAL_DIR": str(tmp_path / "journal"),
                "SOLOMON_DATABASE_URL": f"sqlite:///{tmp_path / 'data' / 'solomon.sqlite3'}",
            },
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == set(available_tool_names())

    anyio.run(call)


def test_stdio_server_calls_preflight_context(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'data' / 'solomon.sqlite3'}"
    service = SolomonService(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        database_url=database_url,
    )
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x under regulation r section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-stdio",
            matter_id="matter-a",
            client_id="client-a",
        )
    )

    async def call() -> None:
        params = StdioServerParameters(
            command="uv",
            args=["run", "python", "-m", "solomon.mcp.server"],
            cwd=Path.cwd(),
            env={
                "SOLOMON_DATA_DIR": str(tmp_path / "data"),
                "SOLOMON_JOURNAL_DIR": str(tmp_path / "journal"),
                "SOLOMON_DATABASE_URL": database_url,
            },
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(
                    "solomon.preflight_context",
                    {
                        "query": "structure x regulation",
                        "matter_id": "matter-a",
                        "client_id": "client-a",
                        "max_items": 1,
                    },
                )
                payload = _structured_payload(result)
                assert payload["items"][0]["item"]["id"] == item.id

    anyio.run(call)


def test_streamable_http_app_exposes_mcp_endpoint(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    app = create_streamable_http_app(service)

    route_paths = {getattr(route, "path", "") for route in app.routes}
    assert "/mcp" in route_paths


def test_uvicorn_config_uses_graceful_shutdown_timeout(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    app = create_streamable_http_app(service)
    config = uvicorn_config_for_app(
        app,
        host="127.0.0.1",
        port=8141,
        shutdown=MCPShutdownConfig(graceful_shutdown_seconds=3),
    )

    assert config.timeout_graceful_shutdown == 3


def test_streamable_http_app_enforces_bearer_token(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    expected = "test-" + "mcp-token"
    app = create_streamable_http_app(service, expected_token=expected)

    async def call(headers: list[tuple[bytes, bytes]]) -> int:
        messages: list[Message] = []

        async def receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            messages.append(message)

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/mcp",
                "raw_path": b"/mcp",
                "query_string": b"",
                "headers": headers,
                "client": ("127.0.0.1", 12345),
                "server": ("127.0.0.1", 8141),
                "state": {},
            },
            receive,
            send,
        )
        start = next(message for message in messages if message["type"] == "http.response.start")
        return int(start["status"])

    assert anyio.run(call, []) == 401
    assert anyio.run(call, [(b"authorization", b"Bearer wrong")]) == 401


def _structured_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        return result[1]
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    raise AssertionError(f"unexpected MCP result shape: {result!r}")
