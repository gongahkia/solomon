# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from solomon.evaluation import (
    DEFAULT_END_TO_END_EVALUATION_CORPUS,
    load_end_to_end_evaluation_corpus,
    run_end_to_end_evaluation,
    write_end_to_end_evaluation_result,
)


def test_public_synthetic_end_to_end_corpus_is_reproducible(tmp_path: Path) -> None:
    corpus = load_end_to_end_evaluation_corpus("docs/evaluation-corpus.e2e.synthetic.json")
    first = run_end_to_end_evaluation(corpus.cases)
    second = run_end_to_end_evaluation(DEFAULT_END_TO_END_EVALUATION_CORPUS.cases)
    result_path = tmp_path / "result.json"
    written = write_end_to_end_evaluation_result(result_path, corpus=corpus)

    assert corpus == DEFAULT_END_TO_END_EVALUATION_CORPUS
    assert first.corpus_sha256 == second.corpus_sha256
    assert first.metrics.extraction_precision == 1.0
    assert first.metrics.extraction_recall == 1.0
    assert first.metrics.graph_impact_recall == 1.0
    assert first.metrics.stale_context_leakage_rate == 0.0
    assert first.metrics.source_to_review_completion_rate == 1.0
    assert first.metrics.mcp_context_recall_after_review == 1.0
    assert written == first
    assert json.loads(result_path.read_text(encoding="utf-8"))["schema_id"] == "solomon.end_to_end_evaluation_result.v1"


def test_end_to_end_evaluation_script_writes_json_result(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "scripts/evaluate_end_to_end.py", "--output", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout)["case_count"] == 2
    assert json.loads(output.read_text(encoding="utf-8"))["metrics"]["stale_context_leakage_rate"] == 0.0
