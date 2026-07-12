# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_scenario() -> ModuleType:
    path = Path("examples/scenarios/03-inhouse-gc/run.py")
    spec = importlib.util.spec_from_file_location("inhouse_gc_scenario", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load in-house GC scenario")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inhouse_gc_pdpa_change_stales_nda_library(tmp_path: Path) -> None:
    result = _load_scenario().run_scenario(tmp_path)

    assert result["company"] == "Lantern Circuit Pte. Ltd."
    assert result["nda_count"] == 12
    assert result["preflight_after"]["items"] == []
    assert result["states"] == ["StalePendingReverification"] * 12
    assert "route the request to Legal" in result["copilot_suggestion"]
    assert result["audit_ok"] is True
