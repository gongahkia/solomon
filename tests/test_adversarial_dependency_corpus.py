# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest

from solomon.adversarial_corpus import (
    AdversarialCorpusIntegrityError,
    corpus_summary,
    load_adversarial_dependency_corpus,
    materialize_mutations,
    resolve_declared_span,
)

CORPUS = Path("examples/scenarios/adversarial-dependency-generalization-proof/corpus/manifest.json")


def test_locked_adversarial_corpus_has_independent_base_fixture_composition() -> None:
    corpus = load_adversarial_dependency_corpus(CORPUS)
    assert corpus["manifest_sha256"] == "bf391fb28a7a76f595aa6399d578bc699c38c3e0745014fd63053ed6a7bf4256"
    assert corpus_summary(corpus) == {
        "items": 84,
        "development": 32,
        "holdout": 52,
        "depends": 35,
        "hard_negatives": 32,
        "ambiguous": 17,
        "mutations": 12,
    }
    for item in corpus["items"]:
        for span in item["reference_spans"]:
            start, end = resolve_declared_span(item["text"], span)
            assert item["text"][start:end] == span["text"]


def test_mutation_manifest_is_fixed_and_label_preserving_at_the_corpus_contract_level() -> None:
    corpus = load_adversarial_dependency_corpus(CORPUS)
    source_items = {item["id"]: item for item in corpus["items"]}
    variants = materialize_mutations(corpus)
    assert len(variants) == 12
    assert len({variant["id"] for variant in variants}) == 12
    for variant in variants:
        source = source_items[variant["source_fixture_id"]]
        assert variant["text"] != source["text"]
        assert variant["expected_suggestions"] == source["expected_suggestions"]


def test_adversarial_manifest_hash_rejects_tampering(tmp_path: Path) -> None:
    tampered = json.loads(CORPUS.read_text(encoding="utf-8"))
    tampered["items"][0]["annotation"] = "changed after corpus lock"
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(AdversarialCorpusIntegrityError, match="hash mismatch"):
        load_adversarial_dependency_corpus(path)
