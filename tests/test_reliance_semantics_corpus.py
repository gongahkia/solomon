# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest

from solomon.reliance_semantics_corpus import (
    RelianceSemanticsCorpusIntegrityError,
    corpus_summary,
    load_reliance_semantics_corpus,
)

CORPUS = Path("examples/scenarios/conservative-reliance-semantics-proof/corpus/manifest.json")


def test_locked_reliance_semantics_corpus_has_required_protocol_distribution() -> None:
    corpus = load_reliance_semantics_corpus(CORPUS)

    assert corpus["status"] == "locked-after-semantics-lock-commit"
    assert corpus_summary(corpus) == {
        "items": 64,
        "development": 24,
        "holdout": 40,
        "depends": 24,
        "hard_negatives": 24,
        "ambiguous": 16,
    }
    assert all(item["confirmed_edge_legal_possible"] is False for item in corpus["items"])


def test_locked_reliance_semantics_corpus_rejects_tampered_raw_text(tmp_path: Path) -> None:
    raw = json.loads(CORPUS.read_text(encoding="utf-8"))
    raw["items"][0]["text"] = "tampered"
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(RelianceSemanticsCorpusIntegrityError, match="hash mismatch"):
        load_reliance_semantics_corpus(tampered)
