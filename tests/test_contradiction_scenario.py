# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _load_example() -> Any:
    path = Path(__file__).resolve().parents[1] / "examples" / "scenarios" / "contradiction" / "run.py"
    spec = importlib.util.spec_from_file_location("contradiction_example", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load contradiction example")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contradiction_scenario_flags_opposing_live_positions(tmp_path: Path) -> None:
    result = _load_example().run_scenario(tmp_path)

    assert result["solomon"]["allow"]["currency"]["currency_state"] == "StalePendingReverification"
    assert result["solomon"]["deny"]["currency"]["currency_state"] == "StalePendingReverification"
    assert (
        result["solomon"]["allow"]["contradictions"][0]["conflicting_item_id"]
        == result["solomon"]["deny"]["item"]["id"]
    )
    assert result["solomon"]["audit_ok"] is True
    assert all(hit["contradiction_signal"] is False for hit in result["warehouse_baseline"])
