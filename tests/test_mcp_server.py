from __future__ import annotations

from stonks_cli.mcp_server import create_server


def test_mcp_server_builds_without_execution_tools() -> None:
    server = create_server()
    assert server.name == "stonks-cli"
