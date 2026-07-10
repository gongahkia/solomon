# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


def test_currency_report_scenario_outputs_partner_headline(tmp_path: Path) -> None:
    module = _load_scenario()

    result = module.run_scenario(tmp_path)

    assert "firm positions" in result["headline"]
    assert result["report"]["totals"]["stale"] == 1
    assert result["report"]["items"][0]["authority_id"] == "reg-r-12"


def _load_scenario() -> ModuleType:
    path = Path("examples/scenarios/currency-report/run.py")
    spec = importlib.util.spec_from_file_location("currency_report_scenario", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load currency report scenario")
    module = importlib.util.module_from_spec(spec)
    loader: Any = spec.loader
    loader.exec_module(module)
    return module
