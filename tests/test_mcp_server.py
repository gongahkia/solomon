from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

import stonks_cli.mcp_server as mcp_server


def _tool(name: str):
    return mcp_server.create_server()._tool_manager.get_tool(name).fn


def test_tools_advertise_safe_annotations():
    server = mcp_server.create_server()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["status"].annotations.readOnlyHint is True
    assert tools["prepare_mutation"].annotations.destructiveHint is True
    assert {"carry_scan", "research_replay_paper", "confirm_mutation"} <= set(tools)


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


<<<<<<< HEAD
def test_readonly_cli_bridge_rejects_mutating_commands():
    result = _tool("cli_readonly")("version")

    assert result["exit_code"] == 0
    with pytest.raises(ValueError, match="not available"):
        _tool("cli_readonly")("clean")


=======
>>>>>>> e181ba5e114ca4956b07dab58f74326f08a9bb01
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
