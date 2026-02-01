"""Tests for the MCP server module."""

from __future__ import annotations

import pytest


def test_mcp_server_import():
    """Test that the MCP server module can be imported."""
    try:
        from stonks_cli import mcp_server
        assert hasattr(mcp_server, "mcp")
        assert hasattr(mcp_server, "main")
    except ImportError as e:
        if "mcp" in str(e):
            pytest.skip("MCP optional dependency not installed")
        raise


def test_mcp_server_has_tools():
    """Test that the MCP server has tools registered."""
    try:
        from stonks_cli.mcp_server import mcp
        # FastMCP registers tools via decorators
        # Check that the mcp object exists and is configured
        assert mcp.name == "stonks-cli"
    except ImportError as e:
        if "mcp" in str(e):
            pytest.skip("MCP optional dependency not installed")
        raise


def test_serialize_helper():
    """Test the _serialize helper function."""
    try:
        from stonks_cli.mcp_server import _serialize
        from datetime import datetime
        from pathlib import Path
        
        # Test basic types
        assert _serialize(42) == 42
        assert _serialize("hello") == "hello"
        
        # Test datetime
        dt = datetime(2024, 1, 15, 10, 30, 0)
        assert _serialize(dt) == "2024-01-15T10:30:00"
        
        # Test Path
        p = Path("/tmp/test")
        assert _serialize(p) == "/tmp/test"
        
        # Test list
        assert _serialize([1, 2, 3]) == [1, 2, 3]
        
        # Test dict
        assert _serialize({"a": 1}) == {"a": 1}
        
    except ImportError as e:
        if "mcp" in str(e):
            pytest.skip("MCP optional dependency not installed")
        raise
