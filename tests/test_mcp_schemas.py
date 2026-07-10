# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from solomon.mcp.schemas import (
    MCP_TOOL_JSON_SCHEMAS,
    TOOL_SCHEMA_MODELS,
    PreflightContextInput,
    json_schema_for_tool,
)

EXPECTED_TOOL_NAMES = {
    "solomon.health",
    "solomon.preflight_context",
    "solomon.check_currency",
    "solomon.get_dependencies",
    "solomon.verify_position",
    "solomon.verification_queue",
    "solomon.ingest",
    "solomon.audit_pack",
    "solomon.currency_report",
    "solomon.dependency_suggestions",
    "solomon.impact",
}
SCHEMA_SNAPSHOT = Path(__file__).parent / "fixtures" / "mcp_tool_schemas.json"


def test_mcp_tool_schemas_cover_required_surface() -> None:
    assert set(TOOL_SCHEMA_MODELS) == EXPECTED_TOOL_NAMES
    assert set(MCP_TOOL_JSON_SCHEMAS) == EXPECTED_TOOL_NAMES


def test_mcp_tool_json_schemas_match_snapshot() -> None:
    expected = json.loads(SCHEMA_SNAPSHOT.read_text(encoding="utf-8"))

    assert MCP_TOOL_JSON_SCHEMAS == expected


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_TOOL_NAMES))
def test_mcp_tool_json_schemas_have_input_and_output(tool_name: str) -> None:
    schema = json_schema_for_tool(tool_name)

    assert set(schema) == {"input", "output"}
    assert schema["input"]["type"] == "object"
    assert schema["output"]["type"] == "object"
    assert schema["input"]["additionalProperties"] is False
    assert schema["output"]["additionalProperties"] is False


def test_mcp_input_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        PreflightContextInput.model_validate({"query": "structure x", "unexpected": True})
