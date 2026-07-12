# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_scenario() -> ModuleType:
    path = Path("examples/scenarios/01-vendor-integration/run.py")
    spec = importlib.util.spec_from_file_location("vendor_integration_scenario", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load vendor-integration scenario")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vendor_integration_smoke_omits_stale_context(tmp_path: Path) -> None:
    result = _load_scenario().run_scenario(tmp_path)

    assert result["vendor"] == "VellumRelay"
    assert result["without_solomon"]["reused_stale_text"] is True
    assert result["with_solomon"]["preflight_after_change"]["items"] == []
    assert result["with_solomon"]["currency"]["state"] == "stale_pending"
    assert result["with_solomon"]["injected_context"] == []
    assert result["with_solomon"]["reused_stale_text"] is False
    message = result["with_solomon"]["assistant_message"]
    assert "depends on Regulation R section 12, which moved on 2025-01-01" in message
    assert result["audit_ok"] is True
