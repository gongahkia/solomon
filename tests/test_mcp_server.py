from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

import stonks_cli.mcp_server as mcp_server


def _tool(name: str):
    return mcp_server.create_server()._tool_manager.get_tool(name).fn


def test_tools_advertise_safe_annotations():
    server = mcp_server.create_server()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["status"].annotations.readOnlyHint is True
    assert tools["prepare_mutation"].annotations.destructiveHint is True
    assert {
        "alert_preview",
        "carry_scan",
        "crypto_rank",
        "moomoo_quotes",
        "portfolio_snapshot",
        "research_replay_paper",
        "reviewed_order_ticket",
        "confirm_mutation",
    } <= set(tools)
    assert tools["moomoo_quotes"].annotations.readOnlyHint is True


def test_status_and_redacted_config(monkeypatch, tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"webhook_url":"https://example.test/secret"}', encoding="utf-8")
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(config))

    assert _tool("status")()["safety"]["live_execution"] == "blocked"
    assert _tool("config_get")()["webhook_url"] == "***REDACTED***"


def test_config_mutation_is_one_time_and_paper_first(monkeypatch, tmp_path):
    config = tmp_path / "config.json"
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(config))
    monkeypatch.setattr(mcp_server, "default_state_dir", lambda: tmp_path / "state")
    prepared = _tool("prepare_mutation")("config_update", {"updates": {"carry.min_net_apr": 0.2}})

    result = _tool("confirm_mutation")(prepared["confirmation_id"])

    assert result["config"]["carry"]["min_net_apr"] == 0.2
    assert result["config"]["carry"]["paper"] is True
    assert result["config"]["carry"]["live_armed"] is False
    with pytest.raises(ValueError, match="unknown or expired"):
        _tool("confirm_mutation")(prepared["confirmation_id"])


def test_config_mutation_rejects_live_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(mcp_server, "default_state_dir", lambda: tmp_path / "state")
    prepared = _tool("prepare_mutation")("config_update", {"updates": {"carry.live_armed": True}})

    with pytest.raises(ValueError, match="only documented safe"):
        _tool("confirm_mutation")(prepared["confirmation_id"])


def test_fixture_scan_respects_configured_roots(monkeypatch, tmp_path):
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("STONKS_CLI_MCP_ROOTS", str(tmp_path))
    fixture = tmp_path / "carry.json"
    fixture.write_text(json.dumps({"inputs": []}), encoding="utf-8")

    assert _tool("carry_scan")(str(fixture))["rows"] == []
    with pytest.raises(ValueError, match="outside"):
        _tool("carry_scan")("/tmp/not-allowed.json")


def test_readonly_cli_bridge_rejects_mutating_commands():
    result = _tool("cli_readonly")("version")

    assert result["exit_code"] == 0
    with pytest.raises(ValueError, match="not available"):
        _tool("cli_readonly")("clean")


def test_first_class_alert_and_reviewed_ticket_never_execute(monkeypatch, tmp_path):
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(tmp_path / "config.json"))

    alert = _tool("alert_preview")("stale_data")
    ticket = _tool("reviewed_order_ticket")(
        "ticket-1",
        "account-1",
        "US.AAPL",
        "buy",
        1.0,
        100.0,
        "USD",
        "synthetic review",
        "2026-01-01T00:00:00+00:00",
        "reviewer",
        "2026-01-01T00:01:00+00:00",
    )

    assert alert["delivery"] == "not_attempted"
    assert alert["synthetic"] is True
    assert ticket["execution"] == "manual broker-app entry required"


def test_http_wrapper_requires_bearer_token():
    events: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        events.append(message)

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    asyncio.run(mcp_server._BearerApp(app, "token")({"type": "http", "headers": []}, receive, send))

    assert events[0]["status"] == 401


def test_stdio_protocol_discovers_and_calls_status(monkeypatch, tmp_path):
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(tmp_path / "config.json"))

    async def run() -> None:
        env = dict(os.environ)
        env["STONKS_CLI_CONFIG"] = str(tmp_path / "config.json")
        env["STONKS_CLI_MCP_ROOTS"] = str(tmp_path)
        params = StdioServerParameters(command=sys.executable, args=["-m", "stonks_cli.mcp_server"], env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                result = await session.call_tool("status", {})
                assert any(tool.name == "status" for tool in tools.tools)
                assert result.structuredContent["safety"]["live_execution"] == "blocked"

    asyncio.run(run())


def test_streamable_http_protocol_requires_token_and_discovers_status(monkeypatch, tmp_path):
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(tmp_path / "config.json"))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()
    env = dict(os.environ)
    env.update(
        {
            "STONKS_CLI_CONFIG": str(tmp_path / "config.json"),
            "STONKS_CLI_MCP_ROOTS": str(tmp_path),
            "STONKS_CLI_MCP_TOKEN": "test-token",
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "stonks_cli.mcp_server", "--transport", "streamable-http", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:

        async def run() -> None:
            deadline = time.monotonic() + 5
            while True:
                try:
                    async with httpx.AsyncClient(headers={"Authorization": "Bearer test-token"}) as client:
                        async with streamable_http_client(f"http://127.0.0.1:{port}/mcp", http_client=client) as (read, write, _):
                            async with ClientSession(read, write) as session:
                                await session.initialize()
                                tools = await session.list_tools()
                                result = await session.call_tool("status", {})
                                assert any(tool.name == "status" for tool in tools.tools)
                                assert result.structuredContent["safety"]["live_execution"] == "blocked"
                                return
                except Exception:
                    if time.monotonic() >= deadline:
                        raise
                    await asyncio.sleep(0.05)

        asyncio.run(run())
    finally:
        process.terminate()
        process.wait(timeout=5)
