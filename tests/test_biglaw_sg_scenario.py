# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_scenario() -> ModuleType:
    path = Path("examples/scenarios/02-biglaw-sg/run.py")
    spec = importlib.util.spec_from_file_location("biglaw_sg_scenario", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load Big Law Singapore scenario")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_biglaw_sg_mas_change_stales_seven_dependent_memos(tmp_path: Path) -> None:
    result = _load_scenario().run_scenario(tmp_path)

    assert result["firm"] == "Meridian Banyan LLP"
    assert result["seeded_internal_items"] == 30
    assert len(result["authority_anchors"]) == 8
    assert result["stale_dependent_count"] == 7
    assert result["states"] == ["StalePendingReverification"] * 7
    assert result["audit_ok"] is True


def test_biglaw_sg_partner_console_walkthrough_resolves_all_review_items(tmp_path: Path) -> None:
    result = _load_scenario().run_partner_console_walkthrough(tmp_path)

    assert result["partner"] == "Partner Tan"
    assert result["reaffirmed_count"] == 3
    assert result["superseded_count"] == 2
    assert result["retired_count"] == 2
    assert result["states"] == ["Live"] * 3 + ["Superseded"] * 2 + ["Retired"] * 2
    assert result["audit_ok"] is True
