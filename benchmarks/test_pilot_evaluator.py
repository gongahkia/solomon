"""Regression tests for the pilot avoided-regression evaluator."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from pilot_evaluator import evaluate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "benchmarks" / "pilot-fixture.json"


class PilotEvaluatorTests(unittest.TestCase):
    def test_observed_avoidance_excludes_unsupported_inference(self) -> None:
        report = evaluate(json.loads(FIXTURE.read_text(encoding="utf-8")))
        self.assertEqual(report["metrics"]["observed_cases"], 2)
        self.assertEqual(report["metrics"]["observed_avoidances"], 1)
        self.assertEqual(report["metrics"]["unsupported_inference_cases"], 1)
        self.assertEqual(report["metrics"]["observed_avoidance_rate"], 0.5)

    def test_cli_writes_failing_case_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output = root / "report.json"
            markdown = root / "report.md"
            replays = root / "replays"
            subprocess.run(
                [
                    "python3", "benchmarks/pilot_evaluator.py", "--input", str(FIXTURE),
                    "--output", str(output), "--markdown", str(markdown), "--replay-dir", str(replays),
                ],
                check=True,
                cwd=ROOT,
            )
            report = json.loads(output.read_text(encoding="utf-8"))
            replay = json.loads((replays / "rejected-decision-repeated.json").read_text(encoding="utf-8"))
            markdown_content = markdown.read_text(encoding="utf-8")
        self.assertEqual(report["baseline"]["name"], "flat-context")
        self.assertEqual(replay["observed_outcome"], "not_avoided")
        self.assertEqual(replay["replay"]["steps"][1]["tool"], "shibahama_memory_review_v1")
        self.assertIn("policy mode", markdown_content)

    def test_observed_outcome_requires_evidence(self) -> None:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["cases"][0]["observed_evidence"] = False
        with self.assertRaisesRegex(ValueError, "observed evidence"):
            evaluate(payload)


if __name__ == "__main__":
    unittest.main()
