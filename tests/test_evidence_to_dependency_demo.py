# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_evidence_to_dependency_proof_headless_demo_matches_deterministic_snapshot(tmp_path: Path) -> None:
    workspace = tmp_path / "evidence-to-dependency-proof"
    subprocess.run(  # noqa: S603 - invokes the repository's fixed local scenario script.
        [
            sys.executable,
            "examples/scenarios/evidence-to-dependency-proof/run.py",
            "--workspace",
            str(workspace),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    expected_path = ROOT / "tests/fixtures/evidence-to-dependency-proof-snapshot.json"
    snapshot_path = workspace / "evidence-to-dependency-proof-snapshot.json"
    result_path = workspace / "evidence-to-dependency-proof-result.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))

    assert snapshot == expected
    assert result["latency_ms"] <= result["latency_budget_ms"]
    assert (workspace / "audit-pack" / "manifest.json").exists()
