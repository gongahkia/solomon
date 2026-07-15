#!/usr/bin/env python3
"""Score auditable stale-citation and rejected-decision pilot cases."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


OUTCOMES = {"avoided", "not_avoided", "unsupported_inference"}
CATEGORIES = {"stale_citation", "rejected_decision"}


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic pilot report or reject malformed evidence."""

    require(payload.get("schema_version") == 1, "schema_version must be 1")
    baseline = require_mapping(payload.get("baseline"), "baseline")
    require(isinstance(baseline.get("name"), str) and baseline["name"], "baseline.name is required")
    policy_mode = payload.get("policy_mode")
    require(isinstance(policy_mode, str) and policy_mode, "policy_mode is required")
    cases = payload.get("cases")
    require(isinstance(cases, list) and cases, "cases must be a non-empty list")

    scored = [score_case(case, baseline, policy_mode) for case in cases]
    observed = [case for case in scored if case["observed_outcome"] != "unsupported_inference"]
    avoided = sum(case["observed_outcome"] == "avoided" for case in observed)
    failures = [case for case in scored if case["observed_outcome"] == "not_avoided"]
    return {
        "schema_version": 1,
        "baseline": baseline,
        "policy_mode": policy_mode,
        "metrics": {
            "observed_cases": len(observed),
            "observed_avoidances": avoided,
            "observed_failures": len(failures),
            "observed_avoidance_rate": avoided / len(observed) if observed else None,
            "unsupported_inference_cases": sum(
                case["observed_outcome"] == "unsupported_inference" for case in scored
            ),
            "mean_token_cost": (
                sum(case["token_cost"] for case in scored) / len(scored) if scored else None
            ),
        },
        "cases": scored,
    }


def score_case(case: Any, baseline: dict[str, Any], policy_mode: str) -> dict[str, Any]:
    """Validate and normalize one replayable pilot case."""

    value = require_mapping(case, "case")
    case_id = value.get("case_id")
    require(isinstance(case_id, str) and case_id, "case_id is required")
    category = value.get("category")
    require(category in CATEGORIES, f"{case_id}: category is invalid")
    outcome = value.get("observed_outcome")
    require(outcome in OUTCOMES, f"{case_id}: observed_outcome is invalid")
    token_cost = value.get("token_cost")
    require(isinstance(token_cost, int) and token_cost >= 0, f"{case_id}: token_cost is invalid")
    baseline_outcome = value.get("baseline_outcome")
    require(isinstance(baseline_outcome, str) and baseline_outcome, f"{case_id}: baseline_outcome is required")
    trace = value.get("explanation_trace")
    require(isinstance(trace, list) and trace, f"{case_id}: explanation_trace is required")
    replay = require_mapping(value.get("replay"), f"{case_id}: replay")
    require(isinstance(replay.get("surface"), str) and replay["surface"], f"{case_id}: replay.surface is required")
    steps = replay.get("steps")
    require(isinstance(steps, list) and steps and all(isinstance(step, dict) for step in steps), f"{case_id}: replay.steps is required")
    if outcome != "unsupported_inference":
        require(bool(value.get("observed_evidence")), f"{case_id}: observed evidence is required")
    return {
        "case_id": case_id,
        "category": category,
        "baseline": baseline,
        "baseline_outcome": baseline_outcome,
        "policy_mode": policy_mode,
        "observed_outcome": outcome,
        "observed_evidence": bool(value.get("observed_evidence")),
        "token_cost": token_cost,
        "explanation_trace": trace,
        "replay": replay,
    }


def write_report(input_path: Path, output_path: Path, markdown_path: Path, replay_dir: Path) -> dict[str, Any]:
    """Evaluate one input file and write report plus failing-case replays."""

    source = json.loads(input_path.read_text(encoding="utf-8"))
    report = evaluate(source)
    report["input_sha256"] = sha256(source)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    replay_dir.mkdir(parents=True, exist_ok=True)
    for case in report["cases"]:
        if case["observed_outcome"] == "not_avoided":
            path = replay_dir / f"{case['case_id']}.json"
            path.write_text(json.dumps(case, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    """Render the claim-bounded pilot report."""

    metrics = report["metrics"]
    return "\n".join([
        "# Pilot Avoided-Regression Report",
        "",
        f"- baseline: `{report['baseline']['name']}`",
        f"- policy mode: `{report['policy_mode']}`",
        f"- input: `sha256:{report['input_sha256']}`",
        "",
        "| observed cases | avoidances | failures | avoidance rate | unsupported inference | mean token cost |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        "| {observed_cases} | {observed_avoidances} | {observed_failures} | {observed_avoidance_rate} | {unsupported_inference_cases} | {mean_token_cost} |".format(
            **{key: format_value(value) for key, value in metrics.items()}
        ),
        "",
        "Observed avoidance requires `observed_evidence`; unsupported inference is excluded from the avoidance rate.",
        "",
    ])


def sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def format_value(value: object) -> str:
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def require_mapping(value: Any, name: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{name} must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--replay-dir", type=Path, required=True)
    args = parser.parse_args()
    write_report(args.input, args.output, args.markdown, args.replay_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
