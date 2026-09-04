# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_scenario() -> ModuleType:
    path = Path("examples/scenarios/05-reference-host-mcp/run.py")
    spec = importlib.util.spec_from_file_location("reference_host_mcp_scenario", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load reference-host MCP scenario")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_host_uses_real_mcp_stdio_transport_and_withholds_stale_context(tmp_path: Path) -> None:
    result = _load_scenario().run_scenario(tmp_path)

    assert result["claims"] == {
        "named_host_compatibility": False,
        "model_or_legal_correctness": False,
        "transport": "MCP stdio",
    }
    assert result["host_policy"] == {
        "principal": "reference-legal-host",
        "read_only_tool_allowlist": ["solomon.preflight_context", "solomon.check_currency"],
        "inject_only_preflight_items": True,
        "fallback": "require_human_reverification",
    }
    proof = result["transport_proof"]
    assert proof["before"]["decision"] == "reuse_current_context"
    assert proof["before"]["injected_item_ids"]
    assert proof["after"] == {
        "decision": "require_human_reverification",
        "injected_item_ids": [],
        "host_message": (
            "The requested firm position is review-due because a recorded dependency changed; "
            "a human must re-verify it before reuse."
        ),
        "excluded_codes": ["stale"],
    }
    assert proof["currency"]["state"] == "stale_pending"
    assert result["audit"] == {"verified": True, "mcp_call_count": 3}
