# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_example() -> ModuleType:
    path = Path("examples/stale-house-view/run.py")
    spec = importlib.util.spec_from_file_location("stale_house_view", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_stale_house_view_scenario_flags_memo_and_baseline_misses(tmp_path: Path) -> None:
    module = _load_example()

    result = module.run_scenario(tmp_path)

    assert result["impact"]["stale_item_ids"] == [result["memo_id"]]
    assert result["solomon_review"][0]["currency_state"] == "StalePendingReverification"
    assert result["warehouse_baseline_top"][0]["item_id"] == result["memo_id"]
    assert result["warehouse_baseline_top"][0]["staleness_signal"] is False
    assert result["model_saw_client_identity"] is False
    assert "[CLIENT_1]" in result["model_saw_text"]
    assert result["audit_report"]["items"][0]["item_id"] == result["memo_id"]
    assert result["audit_report"]["items"][0]["currency_state"] == "StalePendingReverification"
    assert result["audit_chain"]["dependency"] == "reg-r-12"
    assert result["audit_chain"]["dependency_change"]["dependency_id"] == "reg-r-12"
    assert result["audit_chain"]["stale_flag"]["dependency_id"] == "reg-r-12"
    assert "Re-verify before reuse" in result["audit_chain"]["verification_prompt"]
