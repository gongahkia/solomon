from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_synthetic_smoke_script_runs_cli_and_mcp(tmp_path):
    environment = dict(os.environ)
    environment["STONKS_CLI_SMOKE_ROOT"] = str(tmp_path / "smoke")
    completed = subprocess.run(
        [sys.executable, "scripts/smoke_synthetic.py"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.splitlines()[-1])
    manifest = json.loads(Path(result["provenance"]).read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True
    assert manifest["not_validation_evidence"] is True
    assert manifest["cli"]["home"]["safety"]["live_execution"] == "blocked"
    assert manifest["mcp"]["tool_count"] >= 12
