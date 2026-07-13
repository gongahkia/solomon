# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class QualityGate:
    name: str
    command: tuple[str, ...]


QUALITY_GATES = (
    QualityGate(
        "security",
        (sys.executable, "-m", "bandit", "-r", "src/solomon", "--baseline", ".bandit-baseline.json"),
    ),
    QualityGate("performance", (sys.executable, "benchmarks/performance_budget.py")),
    QualityGate("restore", (sys.executable, "-m", "pytest", "tests/test_backup.py")),
    QualityGate(
        "source_review",
        (sys.executable, "-m", "pytest", "tests/test_api_source_workflow.py", "tests/test_review_tasks.py"),
    ),
    QualityGate(
        "no_unsafe_reuse",
        (sys.executable, "-m", "pytest", "tests/test_mcp_runtime.py", "tests/test_mcp_scaffold.py"),
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Solomon pilot-readiness quality gates.")
    parser.add_argument("--gate", action="append", choices=[gate.name for gate in QUALITY_GATES])
    parser.add_argument("--list", action="store_true", help="List gate names and exit.")
    parser.add_argument("--output", type=Path, help="Optional JSON report path.")
    arguments = parser.parse_args()
    if arguments.list:
        print("\n".join(gate.name for gate in QUALITY_GATES))
        return 0
    selected = [gate for gate in QUALITY_GATES if arguments.gate is None or gate.name in arguments.gate]
    results = [_run_gate(gate) for gate in selected]
    payload = {
        "schema_id": "solomon.release_quality_gates.v1",
        "gates": results,
        "passed": all(row["passed"] for row in results),
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(f"{rendered}\n", encoding="utf-8")
    return 0 if payload["passed"] else 1


def _run_gate(gate: QualityGate) -> dict[str, object]:
    started_at = time.perf_counter()
    completed = subprocess.run(gate.command, check=False, capture_output=True, text=True)  # noqa: S603
    return {
        "name": gate.name,
        "passed": completed.returncode == 0,
        "duration_seconds": round(time.perf_counter() - started_at, 3),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


if __name__ == "__main__":
    raise SystemExit(main())
