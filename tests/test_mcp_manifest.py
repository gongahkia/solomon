# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import re
from pathlib import Path

from solomon.mcp.server import available_tool_names

ROOT = Path(__file__).resolve().parent.parent


def test_solomon_mcp_manifest_is_registry_shaped() -> None:
    manifest = json.loads((ROOT / "solomon-mcp.json").read_text(encoding="utf-8"))

    assert manifest["$schema"].endswith("/server.schema.json")
    assert re.fullmatch(r"[a-z0-9][a-z0-9.-]*/[A-Za-z0-9._-]+", manifest["name"])
    assert len(manifest["description"]) <= 100
    assert manifest["version"] == "0.1.0"
    assert manifest["repository"]["source"] == "github"
    assert manifest["icons"][0]["src"].endswith("/docs/assets/solomon-icon.svg")
    assert {remote["type"] for remote in manifest["remotes"]} == {"streamable-http", "sse"}
    assert {remote["headers"][0]["name"] for remote in manifest["remotes"]} == {"Authorization"}


def test_solomon_mcp_manifest_stdio_package_and_tools_match_runtime() -> None:
    manifest = json.loads((ROOT / "solomon-mcp.json").read_text(encoding="utf-8"))
    package = manifest["packages"][0]
    tools = manifest["_meta"]["io.github.gongahkia/solomon"]["tools"]

    assert package["registryType"] == "pypi"
    assert package["identifier"] == "solomon"
    assert package["transport"]["type"] == "stdio"
    assert [argument["value"] for argument in package["packageArguments"]] == ["mcp", "serve"]
    assert [tool["name"] for tool in tools] == sorted(available_tool_names())
    assert {tool["name"] for tool in tools if tool["destructiveHint"]} == {
        "solomon.ingest",
        "solomon.verify_position",
    }
