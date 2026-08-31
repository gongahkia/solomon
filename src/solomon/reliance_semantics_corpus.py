# SPDX-License-Identifier: Apache-2.0

"""Integrity helpers for the independently locked reliance-semantics corpus."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

RELIANCE_SEMANTICS_SCHEMA = "solomon.conservative_reliance_semantics_corpus.v1"
REQUIRED_FIELDS = {
    "id",
    "split",
    "semantic_category",
    "label",
    "text",
    "registered_authority_candidates",
    "scope",
    "reference_spans",
    "raw_evidence_span",
    "expected_suggestions",
    "annotation",
    "expected_suggestion_count",
    "confirmed_edge_legal_possible",
}
ALLOWED_LABELS = {"Depends", "Mentions only", "Contradicts or distinguishes", "Ambiguous", "No relationship"}


class RelianceSemanticsCorpusIntegrityError(ValueError):
    """Raised when locked reliance-semantics labels or raw spans are not trustworthy."""


def canonical_manifest_sha256(manifest: dict[str, Any]) -> str:
    """Return the canonical hash without the self-referential hash field."""

    canonical = dict(manifest)
    canonical.pop("manifest_sha256", None)
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_reliance_semantics_corpus(path: Path | str) -> dict[str, Any]:
    """Load the locked corpus without invoking extraction or persistence."""

    corpus_path = Path(path)
    manifest = cast(dict[str, Any], json.loads(corpus_path.read_text(encoding="utf-8")))
    if manifest.get("schema") != RELIANCE_SEMANTICS_SCHEMA:
        raise RelianceSemanticsCorpusIntegrityError("unsupported reliance semantics corpus schema")
    expected_hash = manifest.get("manifest_sha256")
    if not isinstance(expected_hash, str) or expected_hash != canonical_manifest_sha256(manifest):
        raise RelianceSemanticsCorpusIntegrityError("reliance semantics corpus manifest hash mismatch")
    if manifest.get("status") != "locked-after-semantics-lock-commit":
        raise RelianceSemanticsCorpusIntegrityError("reliance semantics corpus is not locked")
    _validate_items(cast(list[Any], manifest.get("items")))
    return manifest


def corpus_summary(manifest: dict[str, Any]) -> dict[str, int]:
    """Count required split and label distributions for a verified manifest."""

    items = cast(list[dict[str, Any]], manifest["items"])
    return {
        "items": len(items),
        "development": sum(item["split"] == "development" for item in items),
        "holdout": sum(item["split"] == "holdout" for item in items),
        "depends": sum(item["label"] == "Depends" for item in items),
        "hard_negatives": sum(
            item["label"] in {"Mentions only", "Contradicts or distinguishes", "No relationship"} for item in items
        ),
        "ambiguous": sum(item["label"] == "Ambiguous" for item in items),
    }


def resolve_declared_span(text: str, span: dict[str, Any]) -> tuple[int, int]:
    """Resolve a raw label by content and occurrence, failing closed on absence."""

    value = span.get("text")
    occurrence = span.get("occurrence", 0)
    if not isinstance(value, str) or not value or not isinstance(occurrence, int) or occurrence < 0:
        raise RelianceSemanticsCorpusIntegrityError("declared span requires non-empty text and non-negative occurrence")
    start = -1
    position = 0
    for _ in range(occurrence + 1):
        start = text.find(value, position)
        if start < 0:
            raise RelianceSemanticsCorpusIntegrityError(f"declared span is absent from fixture text: {value!r}")
        position = start + len(value)
    return start, start + len(value)


def _validate_items(items: list[Any]) -> None:
    if not isinstance(items, list) or len(items) < 64:
        raise RelianceSemanticsCorpusIntegrityError("reliance semantics corpus requires at least 64 base fixtures")
    identifiers: set[str] = set()
    splits = {"development": 0, "holdout": 0}
    labels = {label: 0 for label in ALLOWED_LABELS}
    for raw_item in items:
        if not isinstance(raw_item, dict) or REQUIRED_FIELDS - raw_item.keys():
            raise RelianceSemanticsCorpusIntegrityError("each reliance fixture must provide all required fields")
        item = cast(dict[str, Any], raw_item)
        item_id = item["id"]
        if not isinstance(item_id, str) or not item_id or item_id in identifiers:
            raise RelianceSemanticsCorpusIntegrityError("reliance fixture IDs must be unique and non-empty")
        identifiers.add(item_id)
        split = item["split"]
        if split not in splits:
            raise RelianceSemanticsCorpusIntegrityError("reliance fixtures must be development or holdout")
        splits[split] += 1
        label = item["label"]
        if label not in ALLOWED_LABELS:
            raise RelianceSemanticsCorpusIntegrityError(f"fixture {item_id} has unsupported label")
        labels[label] += 1
        if not isinstance(item["semantic_category"], str) or not item["semantic_category"]:
            raise RelianceSemanticsCorpusIntegrityError(f"fixture {item_id} lacks a semantic category")
        if not isinstance(item["text"], str) or not item["text"]:
            raise RelianceSemanticsCorpusIntegrityError(f"fixture {item_id} has no raw input text")
        if not isinstance(item["annotation"], str) or not item["annotation"]:
            raise RelianceSemanticsCorpusIntegrityError(f"fixture {item_id} lacks an annotation")
        _validate_scope(item_id, item["scope"])
        candidates = item["registered_authority_candidates"]
        if not isinstance(candidates, list) or not all(isinstance(value, str) and value for value in candidates):
            raise RelianceSemanticsCorpusIntegrityError(f"fixture {item_id} has invalid authority candidates")
        _validate_spans(item_id, item, set(candidates))
    if splits != {"development": 24, "holdout": 40}:
        raise RelianceSemanticsCorpusIntegrityError("reliance corpus must split exactly 24 development and 40 holdout")
    if labels["Depends"] < 24:
        raise RelianceSemanticsCorpusIntegrityError("reliance corpus requires at least 24 affirmative fixtures")
    hard_negatives = labels["Mentions only"] + labels["Contradicts or distinguishes"] + labels["No relationship"]
    if hard_negatives < 24 or labels["Ambiguous"] < 16:
        raise RelianceSemanticsCorpusIntegrityError(
            "reliance corpus lacks required hard-negative or ambiguous fixtures"
        )


def _validate_scope(item_id: str, scope: Any) -> None:
    if not isinstance(scope, dict) or not isinstance(scope.get("tenant_id"), str) or not scope["tenant_id"]:
        raise RelianceSemanticsCorpusIntegrityError(f"fixture {item_id} lacks tenant scope")
    for key in ("matter_id", "client_id"):
        if key in scope and not isinstance(scope[key], str):
            raise RelianceSemanticsCorpusIntegrityError(f"fixture {item_id} has invalid {key}")


def _validate_spans(item_id: str, item: dict[str, Any], candidates: set[str]) -> None:
    text = cast(str, item["text"])
    references = item["reference_spans"]
    suggestions = item["expected_suggestions"]
    if not isinstance(references, list) or not isinstance(suggestions, list):
        raise RelianceSemanticsCorpusIntegrityError(f"fixture {item_id} has invalid span labels")
    for reference in references:
        if not isinstance(reference, dict) or reference.get("target_id") not in candidates:
            raise RelianceSemanticsCorpusIntegrityError(f"fixture {item_id} has an unregistered reference target")
        resolve_declared_span(text, reference)
    evidence = item["raw_evidence_span"]
    if evidence is not None and (not isinstance(evidence, str) or not evidence or evidence not in text):
        raise RelianceSemanticsCorpusIntegrityError(f"fixture {item_id} has an invalid raw evidence span")
    for suggestion in suggestions:
        if not isinstance(suggestion, dict) or suggestion.get("target_id") not in candidates:
            raise RelianceSemanticsCorpusIntegrityError(f"fixture {item_id} has an unregistered suggestion target")
        for key in ("source_span", "target_span"):
            value = suggestion.get(key)
            if not isinstance(value, str) or not value or value not in text:
                raise RelianceSemanticsCorpusIntegrityError(f"fixture {item_id} has an invalid {key}")
        if evidence != suggestion["source_span"]:
            raise RelianceSemanticsCorpusIntegrityError(
                f"fixture {item_id} evidence label must equal suggestion source span"
            )
    if item["expected_suggestion_count"] != len(suggestions):
        raise RelianceSemanticsCorpusIntegrityError(
            f"fixture {item_id} expected suggestion count does not match labels"
        )
    if item["label"] == "Depends" and (not suggestions or evidence is None):
        raise RelianceSemanticsCorpusIntegrityError(f"dependency fixture {item_id} lacks expected raw evidence")
    if item["label"] != "Depends" and (suggestions or evidence is not None):
        raise RelianceSemanticsCorpusIntegrityError(
            f"non-dependency fixture {item_id} must abstain with no evidence span"
        )
