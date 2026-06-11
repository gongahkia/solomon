# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _load_example() -> Any:
    path = Path(__file__).resolve().parents[1] / "examples" / "internal-supersession" / "run.py"
    spec = importlib.util.spec_from_file_location("internal_supersession_example", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load internal supersession example")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_internal_supersession_example_marks_old_position_superseded(tmp_path: Path) -> None:
    result = _load_example().run_scenario(tmp_path)

    assert result["superseded"]["currency_state"] == "Superseded"
    assert result["superseded"]["successor_id"] == "position-2024"
    assert [entry["item"]["id"] for entry in result["default_recall"]] == ["position-2024"]
    assert {entry["item"]["id"] for entry in result["review_recall"]} == {"position-2022", "position-2024"}
    assert result["warehouse_baseline"][0]["supersession_signal"] is False
