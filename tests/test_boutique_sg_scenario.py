# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_scenario() -> ModuleType:
    path = Path("examples/scenarios/04-boutique-sg/run.py")
    spec = importlib.util.spec_from_file_location("boutique_sg_scenario", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load boutique scenario")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_boutique_scenario_stales_only_sparse_privacy_dependencies(tmp_path: Path) -> None:
    result = _load_scenario().run_scenario(tmp_path)

    assert result["firm"] == "Kite & Quoin LLP"
    assert result["lawyer_count"] == 8
    assert result["seeded_memos"] == 50
    assert result["linked_memos"] == 8
    assert len(result["stale_memos"]) == 4
    assert result["audit_ok"] is True
