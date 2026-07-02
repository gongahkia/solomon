"""Regression tests for ContinuityBench metrics."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from continuity.metrics import (
    aggregate_metrics,
    contradiction_is_correct,
    score_dataset,
    spearman_rho,
    supersession_is_stale,
)


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "benchmarks" / "continuity" / "dataset" / "continuitybench-v0.json"


class ContinuityMetricsTests(unittest.TestCase):
    def test_supersession_stale_rule_uses_rank_order(self) -> None:
        self.assertFalse(supersession_is_stale(["current", "stale"], "current", "stale"))
        self.assertTrue(supersession_is_stale(["stale", "current"], "current", "stale"))
        self.assertTrue(supersession_is_stale(["stale"], "current", "stale"))
        self.assertFalse(supersession_is_stale(["other"], "current", "stale"))

    def test_contradiction_rule_requires_authoritative_first(self) -> None:
        self.assertTrue(contradiction_is_correct(["authoritative", "rejected"], "authoritative", "rejected"))
        self.assertFalse(contradiction_is_correct(["rejected", "authoritative"], "authoritative", "rejected"))
        self.assertFalse(contradiction_is_correct(["other"], "authoritative", "rejected"))

    def test_spearman_rho_handles_order_and_ties(self) -> None:
        self.assertAlmostEqual(spearman_rho([(0.1, 1), (0.2, 2), (0.9, 4)]), 1.0)
        self.assertAlmostEqual(spearman_rho([(0.9, 1), (0.2, 2), (0.1, 4)]), -1.0)
        self.assertIsNone(spearman_rho([(0.5, 1)]))

    def test_score_dataset_reports_all_phase_b_metrics(self) -> None:
        dataset = json.loads(DATASET.read_text(encoding="utf-8"))
        tasks = {
            category: next(task for task in dataset["tasks"] if task["category"] == category)
            for category in ["supersession", "contradiction", "evidence-quality", "stable-recall"]
        }
        subset = {"tasks": list(tasks.values())}
        outputs = {
            "results": [
                output_for(tasks["supersession"], [tasks["supersession"]["answers"]["stale"]], [0.1]),
                output_for(
                    tasks["contradiction"],
                    [tasks["contradiction"]["answers"]["authoritative"]],
                    [0.9],
                ),
                output_for(
                    tasks["evidence-quality"],
                    [tasks["evidence-quality"]["answers"]["current"]],
                    [0.7],
                ),
                output_for(
                    tasks["stable-recall"],
                    [tasks["stable-recall"]["answers"]["current"]],
                    [0.6],
                ),
            ]
        }

        scored = score_dataset(subset, outputs)

        self.assertEqual(scored["metrics"]["stale_answer_rate"], 1.0)
        self.assertEqual(scored["metrics"]["contradiction_resolution_acc"], 1.0)
        self.assertEqual(scored["metrics"]["credence_n"], 1)
        self.assertEqual(scored["metrics"]["mean_retrieval_tokens"], 2.0)
        self.assertEqual(scored["metrics"]["stable_recall_acc"], 1.0)

    def test_score_cli_writes_json_and_markdown(self) -> None:
        dataset = json.loads(DATASET.read_text(encoding="utf-8"))
        task = next(task for task in dataset["tasks"] if task["category"] == "stable-recall")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            system_output = tmp / "system.json"
            output = tmp / "result.json"
            markdown = tmp / "result.md"
            system_output.write_text(
                json.dumps(
                    {
                        "system": "fixture",
                        "model": "none",
                        "seed": 0,
                        "tokenizer": "whitespace",
                        "results": [output_for(task, [task["answers"]["current"]], [0.8])],
                    }
                ),
                encoding="utf-8",
            )

            import subprocess

            subprocess.run(
                [
                    "python3",
                    "benchmarks/continuity/score.py",
                    "--dataset",
                    str(DATASET),
                    "--system-output",
                    str(system_output),
                    "--output",
                    str(output),
                    "--markdown",
                    str(markdown),
                ],
                check=True,
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
            )

            result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result["manifest"]["system"], "fixture")
        self.assertTrue(result["manifest"]["dataset_hash"].startswith("sha256:"))
        self.assertIn("stable_recall_acc", result["metrics"])


def output_for(task: dict[str, object], contexts: list[str], credences: list[float]) -> dict[str, object]:
    return {
        "task_id": str(task["task_id"]),
        "contexts": contexts,
        "item_credences": credences,
        "token_count": 2,
    }


if __name__ == "__main__":
    unittest.main()
