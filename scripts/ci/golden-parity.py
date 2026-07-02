#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the golden-vector parity suite across Rust, Python, and Node."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "scripts" / "ci" / "golden-parity.json"
PY_BINDING = ROOT / "bindings" / "python" / "python"
if PY_BINDING.exists():
    sys.path.insert(0, str(PY_BINDING))


def main() -> int:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    expected = fixture["expected"]
    outputs = {
        "python": run_python_lane(fixture),
        "node": run_json_command(
            ["node", "scripts/ci/golden-parity-node.mjs", str(FIXTURE)],
        ),
        "rust": run_json_command(
            [
                "cargo",
                "run",
                "-q",
                "--manifest-path",
                "core/Cargo.toml",
                "--example",
                "golden_parity",
                "--",
                str(FIXTURE),
            ],
        ),
    }

    failures: list[str] = []
    for lane, output in outputs.items():
        if output != expected:
            failures.append(diff_payload(lane, expected, output))

    if failures:
        print("\n\n".join(failures), file=sys.stderr)
        return 1

    print("golden parity passed: rust, python, node")
    return 0


def run_json_command(command: list[str]) -> dict[str, Any]:
    output = subprocess.check_output(command, cwd=ROOT, text=True)
    return json.loads(output)


def run_python_lane(fixture: dict[str, Any]) -> dict[str, Any]:
    import shibahama

    with tempfile.NamedTemporaryFile() as store:
        engine = shibahama.Shibahama(
            store.name,
            fixture["dimensions"],
            fixture["capacity"],
        )
        ids: dict[str, str] = {}
        output: dict[str, Any] = {"queries": [], "memories": [], "why": []}

        for step in fixture["steps"]:
            if step["op"] == "write":
                item = engine.write(
                    step["content"],
                    vector=step["vector"],
                    source_kind=step["source_kind"],
                    source_ref=step["source_ref"],
                    ingested_by=step["ingested_by"],
                    valid_from_unix=step["valid_from_unix"],
                    ingested_at_unix=step["ingested_at_unix"],
                )
                ids[step["source_ref"]] = item.id
            elif step["op"] == "invalidate":
                if not engine.invalidate(ids[step["source_ref"]], step["valid_to_unix"]):
                    raise AssertionError(f"failed to invalidate {step['source_ref']}")
            else:
                raise AssertionError(f"unknown step op: {step['op']}")

        for query in fixture["queries"]:
            recalled = engine.recall(
                query["vector"],
                query["top_k"],
                now_unix=query["now_unix"],
                raw_query_context=query["raw_query_context"],
                include_cold=query["include_cold"],
            )
            output["queries"].append(
                {
                    "name": query["name"],
                    "recall": [normalize_python_candidate(candidate) for candidate in recalled],
                }
            )

        memories = sorted(
            [normalize_python_memory(memory) for memory in engine.memory_items()],
            key=lambda memory: memory["source_ref"],
        )
        output["memories"] = memories
        output["why"] = [
            normalize_python_why(
                require_trace(engine.why(ids[memory["source_ref"]], fixture["why_now_unix"]))
            )
            for memory in memories
        ]

    return output


def normalize_python_candidate(candidate: Any) -> dict[str, Any]:
    return {
        "source_ref": candidate.item.provenance.source_ref,
        "tier": candidate.tier,
        "credence": candidate.item.credence,
        "currency": candidate.currency,
        "significance_score": fixed(candidate.significance_score),
        "rank_score": fixed(candidate.rank_score),
    }


def normalize_python_memory(memory: Any) -> dict[str, Any]:
    return {
        "source_ref": memory.provenance.source_ref,
        "tier": memory.tier,
        "credence": memory.credence,
        "significance": fixed(memory.significance),
        "valid_to_unix": memory.valid_to_unix,
    }


def normalize_python_why(trace: Any) -> dict[str, Any]:
    return {
        "source_ref": trace.item.provenance.source_ref,
        "currency_state": trace.currency_state,
        "tier_current": trace.tier_current,
        "tier_credence": trace.tier_credence,
        "final_score": fixed(trace.significance.final_score),
        "valid_to_unix": trace.valid_to_unix,
    }


def require_trace(trace: Any | None) -> Any:
    if trace is None:
        raise AssertionError("missing why trace")
    return trace


def fixed(value: float) -> str:
    return f"{value:.6f}"


def diff_payload(lane: str, expected: dict[str, Any], actual: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"{lane} parity mismatch",
            "expected:",
            json.dumps(expected, indent=2, sort_keys=True),
            "actual:",
            json.dumps(actual, indent=2, sort_keys=True),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
