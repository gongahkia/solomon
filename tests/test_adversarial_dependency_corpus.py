# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest

from solomon.adversarial_corpus import (
    AdversarialCorpusIntegrityError,
    canonical_manifest_sha256,
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


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema", "unsupported", "unsupported"),
        ("status", "draft", "not locked"),
    ],
)
def test_adversarial_manifest_rejects_invalid_top_level_contract(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    invalid = json.loads(CORPUS.read_text(encoding="utf-8"))
    invalid[field] = value
    invalid["manifest_sha256"] = canonical_manifest_sha256(invalid)
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(invalid), encoding="utf-8")

    with pytest.raises(AdversarialCorpusIntegrityError, match=message):
        load_adversarial_dependency_corpus(path)


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("too_few_items", "at least 80"),
        ("missing_field", "all required fields"),
        ("duplicate_id", "unique"),
        ("invalid_split", "development or holdout"),
        ("invalid_label", "unsupported label"),
        ("empty_text", "has no input text"),
        ("missing_tenant", "lacks tenant scope"),
        ("invalid_candidates", "invalid authority candidates"),
        ("invalid_spans", "invalid span labels"),
        ("unregistered_suggestion", "unregistered suggestion"),
        ("invalid_count", "count does not match"),
        ("too_few_mutations", "at least 12"),
    ],
)
def test_adversarial_manifest_rejects_invalid_fixture_and_mutation_contracts(
    tmp_path: Path, kind: str, message: str
) -> None:
    invalid = json.loads(CORPUS.read_text(encoding="utf-8"))
    first = invalid["items"][0]
    if kind == "too_few_items":
        invalid["items"] = []
    elif kind == "missing_field":
        first.pop("annotation")
    elif kind == "duplicate_id":
        invalid["items"][1]["id"] = first["id"]
    elif kind == "invalid_split":
        first["split"] = "draft"
    elif kind == "invalid_label":
        first["label"] = "Maybe"
    elif kind == "empty_text":
        first["text"] = ""
    elif kind == "missing_tenant":
        first["scope"] = {}
    elif kind == "invalid_candidates":
        first["registered_authority_candidates"] = "authority"
    elif kind == "invalid_spans":
        first["reference_spans"] = "authority"
    elif kind == "unregistered_suggestion":
        first["expected_suggestions"][0]["target_id"] = "unregistered"
    elif kind == "invalid_count":
        first["expected_suggestion_count"] = 99
    elif kind == "too_few_mutations":
        invalid["mutations"] = []
    invalid["manifest_sha256"] = canonical_manifest_sha256(invalid)
    path = tmp_path / f"{kind}.json"
    path.write_text(json.dumps(invalid), encoding="utf-8")

    with pytest.raises(AdversarialCorpusIntegrityError, match=message):
        load_adversarial_dependency_corpus(path)


def test_span_and_mutation_materialization_reject_invalid_declared_input() -> None:
    with pytest.raises(AdversarialCorpusIntegrityError, match="non-empty text"):
        resolve_declared_span("source", {"text": "", "occurrence": 0})
    with pytest.raises(AdversarialCorpusIntegrityError, match="absent"):
        resolve_declared_span("source", {"text": "missing"})

    corpus = load_adversarial_dependency_corpus(CORPUS)
    corpus["mutations"][0]["transformation"] = "declared_alias_substitution"
    with pytest.raises(AdversarialCorpusIntegrityError, match="did not change"):
        materialize_mutations(corpus)
