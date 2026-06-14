# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from solomon import __version__
from solomon.mcp.auth import MCPAuthConfig, bearer_token_matches, token_from_env
from solomon.mcp.logging import hash_mcp_input
from solomon.mcp.server import available_tool_names, create_server_config
from solomon.mcp.tools import READ_ONLY_TOOLS, mcp_tool_specs
from solomon.mcp.transport import MCPTransportConfig


def test_mcp_server_config_exposes_all_schema_tools() -> None:
    config = create_server_config(version=__version__)

    assert config.name == "solomon"
    assert config.transport.kind == "stdio"
    assert len(config.tools) == 8
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
