# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_adversarial_dependency_generalization_headless_demo_matches_snapshot(tmp_path: Path) -> None:
    workspace = tmp_path / "adversarial-dependency-generalization-proof"
    subprocess.run(  # noqa: S603 - invokes the repository's fixed local scenario script.
        [
            sys.executable,
            "examples/scenarios/adversarial-dependency-generalization-proof/run.py",
            "--workspace",
            str(workspace),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    expected = json.loads(
        (ROOT / "tests/fixtures/adversarial-dependency-generalization-snapshot.json").read_text(encoding="utf-8")
    )
    snapshot = json.loads(
        (workspace / "adversarial-dependency-generalization-snapshot.json").read_text(encoding="utf-8")
    )
    result = json.loads((workspace / "adversarial-dependency-generalization-result.json").read_text(encoding="utf-8"))

    assert snapshot == expected
    assert result["latency_ms"] <= result["latency_budget_ms"]
    assert (workspace / "audit-pack" / "manifest.json").exists()
