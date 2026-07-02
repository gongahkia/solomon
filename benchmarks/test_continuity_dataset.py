"""Regression tests for the ContinuityBench v0 dataset."""

from __future__ import annotations

import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "benchmarks" / "continuity" / "dataset" / "continuitybench-v0.json"
HASH = DATASET.with_suffix(".sha256")


class ContinuityDatasetTests(unittest.TestCase):
    def test_dataset_hash_matches_canonical_json(self) -> None:
        dataset = json.loads(DATASET.read_text(encoding="utf-8"))
        canonical = json.dumps(dataset, sort_keys=True, separators=(",", ":")).encode("utf-8")
        expected = HASH.read_text(encoding="utf-8").split()[0]

        self.assertEqual(f"sha256:{hashlib.sha256(canonical).hexdigest()}", expected)

    def test_dataset_has_required_size_and_distribution(self) -> None:
        dataset = json.loads(DATASET.read_text(encoding="utf-8"))
        tasks = dataset["tasks"]

        self.assertEqual(dataset["schema_version"], "continuitybench.v0")
        self.assertEqual(len(tasks), 200)
        self.assertEqual(
            Counter(task["category"] for task in tasks),
            {
                "supersession": 80,
                "contradiction": 50,
                "evidence-quality": 40,
                "stable-recall": 30,
            },
        )
        self.assertEqual(Counter(task["domain"] for task in tasks), {"coding": 160, "general": 40})

    def test_task_schema_supports_phase_b_metrics(self) -> None:
        dataset = json.loads(DATASET.read_text(encoding="utf-8"))
        task_ids = set()

        for task in dataset["tasks"]:
            task_id = task["task_id"]
            self.assertNotIn(task_id, task_ids)
            task_ids.add(task_id)
            self.assertIn(task["category"], {"supersession", "contradiction", "evidence-quality", "stable-recall"})
            self.assertIn(task["domain"], {"coding", "general"})
            self.assertTrue(task["events"])
            self.assertIn("target_fact", task["query"])
            self.assertIn("answers", task)

            event_ids = {event["event_id"] for event in task["events"]}
            established = {event["establishes"] for event in task["events"]}
            self.assertIn(task["query"]["target_fact"], established)

            for event in task["events"]:
                self.assertIn("content", event)
                self.assertIn("t", event)
                self.assertIn("provenance", event)
                self.assertIn("kind", event["provenance"])
                self.assertIn("corroboration", event["provenance"])

            if task["category"] == "supersession":
                self.assertIn("current", task["answers"])
                self.assertIn("stale", task["answers"])
                self.assertTrue(any(event["supersedes"] for event in task["events"]))
            elif task["category"] == "contradiction":
                self.assertIn(task["resolution"]["authoritative_event_id"], event_ids)
                self.assertIn("authoritative", task["answers"])
                self.assertIn("rejected", task["answers"])
            elif task["category"] == "evidence-quality":
                strength = task["evidence"]["strength"]
                self.assertIn(strength, {1, 2, 3, 4})
                self.assertEqual(task["events"][0]["provenance"]["evidence_strength"], strength)
            elif task["category"] == "stable-recall":
                self.assertIn("current", task["answers"])
                self.assertFalse(any(event["supersedes"] for event in task["events"]))


if __name__ == "__main__":
    unittest.main()
