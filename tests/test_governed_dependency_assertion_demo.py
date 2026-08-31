# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_governed_dependency_assertion_proof_matches_deterministic_snapshot(tmp_path: Path) -> None:
    workspace = tmp_path / "governed-dependency-assertion-proof"
    subprocess.run(  # noqa: S603 - invokes the repository's fixed local scenario script.
        [
            sys.executable,
            "examples/scenarios/governed-dependency-assertion-proof/run.py",
            "--workspace",
            str(workspace),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    expected = json.loads(
        (ROOT / "tests/fixtures/governed-dependency-assertion-proof-snapshot.json").read_text(encoding="utf-8")
    )
    snapshot = json.loads((workspace / "governed-dependency-assertion-proof-snapshot.json").read_text(encoding="utf-8"))
    result = json.loads((workspace / "governed-dependency-assertion-proof-result.json").read_text(encoding="utf-8"))

    assert snapshot == expected
    assert result["latency_ms"] <= result["latency_budget_ms"]
    assert (workspace / "audit-pack" / "manifest.json").exists()
