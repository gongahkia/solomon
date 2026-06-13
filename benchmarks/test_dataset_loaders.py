"""Regression tests for official benchmark dataset loaders."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shibahama_bench.tasks import load_suite


class DatasetLoaderTests(unittest.TestCase):
    def test_locomo_loader_accepts_official_json_export_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dataset = Path(tmpdir) / "locomo10.json"
            dataset.write_text(
                json.dumps(
                    [
                        {
                            "sample_id": "sample-1",
                            "conversation": {
                                "session_1_date_time": "1:56 pm on 8 May, 2023",
                                "session_1": [
                                    {
                                        "speaker": "Caroline",
                                        "dia_id": "D1:3",
                                        "text": "I went to a LGBTQ support group yesterday.",
                                    }
                                ],
                            },
                            "observation": {
                                "session_1_observation": {
                                    "Caroline": [
                                        [
                                            "Caroline attended an LGBTQ support group recently.",
                                            "D1:3",
                                        ]
                                    ]
                                }
                            },
                            "qa": [
                                {
                                    "question": "When did Caroline go to the support group?",
                                    "answer": "7 May 2023",
                                    "evidence": ["D1:3"],
                                    "category": 2,
                                }
                            ],
                        }
                    ]
                ),
                encoding="utf-8",
            )

            cases = load_suite("locomo", dataset)

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].name, "sample-1")
        self.assertEqual(cases[0].metadata["suite"], "locomo")
        self.assertEqual(cases[0].metadata["source_format"], "official-locomo-json")
        self.assertEqual(cases[0].observations[0].source_ref, "sample-1:D1:3")
        self.assertIn("support group", cases[0].observations[0].content)
        self.assertEqual(cases[0].queries[0].expected, "7 May 2023")

    def test_longmemeval_loader_accepts_official_json_export_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dataset = Path(tmpdir) / "longmemeval_s_cleaned.json"
            dataset.write_text(
                json.dumps(
                    [
                        {
                            "question_id": "e47becba",
                            "question_type": "single-session-user",
                            "question": "What degree did I graduate with?",
                            "answer": "Business Administration",
                            "question_date": "2023/05/30 (Tue) 23:40",
                            "haystack_session_ids": ["answer_280352e9"],
                            "haystack_dates": ["2023/05/20 (Sat) 02:57"],
                            "haystack_sessions": [
                                [
                                    {
                                        "role": "user",
                                        "content": "I graduated with Business Administration.",
                                    },
                                    {"role": "assistant", "content": "Congratulations."},
                                ]
                            ],
                            "answer_session_ids": ["answer_280352e9"],
                        }
                    ]
                ),
                encoding="utf-8",
            )

            cases = load_suite("longmemeval", dataset)

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].name, "e47becba")
        self.assertEqual(cases[0].metadata["suite"], "longmemeval")
        self.assertEqual(cases[0].metadata["source_format"], "official-longmemeval-json")
        self.assertEqual(cases[0].metadata["question_type"], "single-session-user")
        self.assertEqual(cases[0].observations[0].source_ref, "e47becba:answer_280352e9")
        self.assertIn("Business Administration", cases[0].observations[0].content)
        self.assertEqual(cases[0].queries[0].expected, "Business Administration")


if __name__ == "__main__":
    unittest.main()
