# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_currency_loop_proof_headless_demo_matches_deterministic_snapshot(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "currency-loop-proof"
    completed = subprocess.run(  # noqa: S603 - fixed in-repository scenario command.
        [
            sys.executable,
            "examples/scenarios/currency-loop-proof/run.py",
            "--workspace",
            str(workspace),
        ],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    expected = json.loads((repository / "tests/fixtures/currency-loop-proof-snapshot.json").read_text(encoding="utf-8"))
    snapshot = json.loads((workspace / "currency-loop-proof-snapshot.json").read_text(encoding="utf-8"))
    result = json.loads((workspace / "currency-loop-proof-result.json").read_text(encoding="utf-8"))

    assert json.loads(completed.stdout) == expected
    assert snapshot == expected
    assert result["latency_ms"] <= result["latency_budget_ms"]
    assert (workspace / "audit-pack" / "manifest.json").exists()
