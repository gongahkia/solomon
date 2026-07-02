#!/usr/bin/env python3
"""Score ContinuityBench system outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from metrics import score_dataset


DEFAULT_DATASET = Path(__file__).with_name("dataset") / "continuitybench-v0.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--system-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()

    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    system_output = json.loads(args.system_output.read_text(encoding="utf-8"))
    scored = score_dataset(dataset, system_output)
    payload = {
        "manifest": manifest(dataset, system_output),
        **scored,
    }
    payload["manifest"]["command"] = shlex.join(sys.argv)
    payload["manifest"]["timestamp_utc"] = datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(markdown(payload), encoding="utf-8")
    print(f"wrote {args.output}")
    print(f"wrote {args.markdown}")
    return 0


def manifest(dataset: dict[str, Any], system_output: dict[str, Any]) -> dict[str, Any]:
    return {
        "system": str(system_output.get("system", "unknown")),
        "dataset_hash": f"sha256:{dataset_hash(dataset)}",
        "model": system_output.get("model", "none"),
        "seed": system_output.get("seed"),
        "tokenizer": system_output.get("tokenizer", "reported-by-adapter"),
        "judge_prompt_hash": system_output.get("judge_prompt_hash"),
    }


def dataset_hash(dataset: dict[str, Any]) -> str:
    canonical = json.dumps(dataset, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def markdown(payload: dict[str, Any]) -> str:
    metrics = payload["metrics"]
    manifest_data = payload["manifest"]
    return "\n".join(
        [
            "# ContinuityBench Result",
            "",
            f"- system: `{manifest_data['system']}`",
            f"- dataset: `{manifest_data['dataset_hash']}`",
            f"- tokenizer: `{manifest_data['tokenizer']}`",
            "",
            "| stale-answer rate | contradiction acc | credence rho | credence n | mean tokens | stable recall acc |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
            "| {stale} | {contradiction} | {rho} | {n} | {tokens} | {stable} |".format(
                stale=format_value(metrics["stale_answer_rate"]),
                contradiction=format_value(metrics["contradiction_resolution_acc"]),
                rho=format_value(metrics["credence_tracks_evidence_rho"]),
                n=format_value(metrics["credence_n"]),
                tokens=format_value(metrics["mean_retrieval_tokens"]),
                stable=format_value(metrics["stable_recall_acc"]),
            ),
            "",
        ]
    )


def format_value(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
