from __future__ import annotations

from pathlib import Path

from stonks_cli.config import ProfileConfig, save_profile
from stonks_cli.mcp_server import _MCP_TOOL_ALLOWLIST, _validate_tool_registry, create_server
from stonks_cli.storage import EncryptedLedger, generate_key_file


def test_mcp_server_builds_without_execution_tools() -> None:
    server = create_server()
    assert server.name == "stonks-cli"
    assert set(server._tool_manager._tools) == _MCP_TOOL_ALLOWLIST


def test_mcp_registry_rejects_added_execution_tool() -> None:
    server = create_server()
    server._tool_manager._tools["place_order"] = object()

    try:
        _validate_tool_registry(server)
    except RuntimeError as error:
        assert "prohibited" in str(error)
    else:
        raise AssertionError("MCP execution tool must be rejected")


def test_mcp_provider_change_requires_single_use_confirmation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    key = tmp_path / "key"
    generate_key_file(key)
    save_profile(ProfileConfig("personal", str(key)))
    tools = create_server()._tool_manager._tools

    prepared = tools["prepare_provider_change"].fn("personal", "moomoo", False)
    result = tools["confirm_provider_change"].fn(str(prepared["confirmation_id"]))

    assert result["providers"] == ["csv"]
    with EncryptedLedger(ProfileConfig("personal", str(key))).connection() as connection:
        events = [row["event"] for row in connection.execute("SELECT event FROM mcp_mutation_audit")]
    assert events == ["requested", "confirmed", "completed"]
    try:
        tools["confirm_provider_change"].fn(str(prepared["confirmation_id"]))
    except ValueError as error:
        assert "invalid" in str(error)
    else:
        raise AssertionError("MCP confirmation must be single-use")
