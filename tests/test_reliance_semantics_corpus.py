# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from solomon.reliance_semantics_corpus import (
    RelianceSemanticsCorpusIntegrityError,
    canonical_manifest_sha256,
    corpus_summary,
    load_reliance_semantics_corpus,
    resolve_declared_span,
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


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda manifest: manifest.update(schema="unsupported"), "unsupported reliance semantics corpus schema"),
        (lambda manifest: manifest.update(status="draft"), "reliance semantics corpus is not locked"),
        (
            lambda manifest: manifest["items"][0].update(expected_suggestion_count=0),
            "expected suggestion count does not match labels",
        ),
        (
            lambda manifest: manifest["items"][9].update(raw_evidence_span="unexpected evidence"),
            "invalid raw evidence span",
        ),
        (
            lambda manifest: manifest["items"][0]["scope"].update(matter_id=1),
            "invalid matter_id",
        ),
        (
            lambda manifest: manifest["items"][0].update(registered_authority_candidates=[" "]),
            "unregistered reference target",
        ),
    ),
)
def test_locked_reliance_semantics_corpus_rejects_signed_invalid_labels(
    tmp_path: Path, mutation: Any, message: str
) -> None:
    manifest = _manifest()
    mutation(manifest)
    path = _write_signed_manifest(tmp_path, manifest)

    with pytest.raises(RelianceSemanticsCorpusIntegrityError, match=message):
        load_reliance_semantics_corpus(path)


def test_locked_reliance_semantics_corpus_rejects_bad_split_and_nonaffirmative_evidence(tmp_path: Path) -> None:
    bad_split = _manifest()
    bad_split["items"][0]["split"] = "preview"
    with pytest.raises(RelianceSemanticsCorpusIntegrityError, match="development or holdout"):
        load_reliance_semantics_corpus(_write_signed_manifest(tmp_path, bad_split, "bad-split.json"))

    nonaffirmative_evidence = _manifest()
    nonaffirmative_evidence["items"][9]["raw_evidence_span"] = nonaffirmative_evidence["items"][9]["text"]
    with pytest.raises(RelianceSemanticsCorpusIntegrityError, match="must abstain"):
        load_reliance_semantics_corpus(_write_signed_manifest(tmp_path, nonaffirmative_evidence, "bad-evidence.json"))


def _remove_affirmative_for_label_gate(manifest: dict[str, Any]) -> None:
    item = manifest["items"][0]
    item.update(label="Mentions only", raw_evidence_span=None, expected_suggestions=[], expected_suggestion_count=0)


def _remove_ambiguous_for_label_gate(manifest: dict[str, Any]) -> None:
    item = next(item for item in manifest["items"] if item["label"] == "Ambiguous")
    item["label"] = "Mentions only"


def _remove_positive_evidence(manifest: dict[str, Any]) -> None:
    manifest["items"][0].update(raw_evidence_span=None, expected_suggestions=[], expected_suggestion_count=0)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda manifest: manifest.update(items=[]), "at least 64 base fixtures"),
        (lambda manifest: manifest["items"][0].pop("annotation"), "all required fields"),
        (lambda manifest: manifest["items"][1].update(id=manifest["items"][0]["id"]), "unique and non-empty"),
        (lambda manifest: manifest["items"][0].update(label="Unknown"), "unsupported label"),
        (lambda manifest: manifest["items"][0].update(semantic_category=""), "lacks a semantic category"),
        (lambda manifest: manifest["items"][0].update(text=""), "no raw input text"),
        (lambda manifest: manifest["items"][0].update(annotation=""), "lacks an annotation"),
        (lambda manifest: manifest["items"][0]["scope"].update(tenant_id=""), "lacks tenant scope"),
        (
            lambda manifest: manifest["items"][0].update(registered_authority_candidates=[""]),
            "invalid authority candidates",
        ),
        (lambda manifest: manifest["items"][0].update(reference_spans={}), "invalid span labels"),
        (
            lambda manifest: manifest["items"][0]["expected_suggestions"][0].update(target_id="unregistered"),
            "unregistered suggestion target",
        ),
        (
            lambda manifest: manifest["items"][0]["expected_suggestions"][0].update(source_span="absent"),
            "invalid source_span",
        ),
        (
            lambda manifest: manifest["items"][0].update(raw_evidence_span="Atlas Regulation 12 section 4"),
            "evidence label must equal suggestion source span",
        ),
        (lambda manifest: manifest["items"][0].update(split="holdout"), "split exactly 24 development and 40 holdout"),
        (_remove_affirmative_for_label_gate, "requires at least 24 affirmative fixtures"),
        (_remove_ambiguous_for_label_gate, "lacks required hard-negative or ambiguous fixtures"),
        (_remove_positive_evidence, "lacks expected raw evidence"),
    ),
)
def test_locked_reliance_semantics_corpus_rejects_each_labeled_invariant(
    tmp_path: Path, mutation: Any, message: str
) -> None:
    manifest = _manifest()
    mutation(manifest)

    with pytest.raises(RelianceSemanticsCorpusIntegrityError, match=message):
        load_reliance_semantics_corpus(_write_signed_manifest(tmp_path, manifest))


def test_declared_span_resolution_handles_occurrences_and_rejects_invalid_values() -> None:
    assert resolve_declared_span("Atlas Act 1; Atlas Act 1", {"text": "Atlas Act 1", "occurrence": 1}) == (13, 24)
    for span in ({"text": ""}, {"text": "missing"}, {"text": "Atlas", "occurrence": -1}):
        with pytest.raises(RelianceSemanticsCorpusIntegrityError):
            resolve_declared_span("Atlas Act 1", span)


def _manifest() -> dict[str, Any]:
    return deepcopy(json.loads(CORPUS.read_text(encoding="utf-8")))


def _write_signed_manifest(tmp_path: Path, manifest: dict[str, Any], name: str = "invalid.json") -> Path:
    manifest["manifest_sha256"] = canonical_manifest_sha256(manifest)
    path = tmp_path / name
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path
