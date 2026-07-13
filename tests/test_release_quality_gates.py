# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_release_quality_gate_runner_lists_and_executes_selected_gate(tmp_path: Path) -> None:
    listed = subprocess.run(  # noqa: S603
        [sys.executable, "scripts/release_quality_gates.py", "--list"],
        check=True,
        capture_output=True,
        text=True,
    )
    output = tmp_path / "quality-gates.json"
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "scripts/release_quality_gates.py", "--gate", "restore", "--output", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert listed.stdout.splitlines() == ["security", "performance", "restore", "source_review", "no_unsafe_reuse"]
    payload = json.loads(completed.stdout)
    assert payload["passed"] is True
    assert payload["gates"][0]["name"] == "restore"
    assert json.loads(output.read_text(encoding="utf-8"))["schema_id"] == "solomon.release_quality_gates.v1"
