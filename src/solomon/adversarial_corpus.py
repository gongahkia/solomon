# SPDX-License-Identifier: Apache-2.0

"""Integrity and deterministic mutation support for the locked adversarial corpus."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, cast

CHALLENGE_SCHEMA = "solomon.adversarial_dependency_challenge.v1"
REQUIRED_FIELDS = {
    "id",
    "split",
    "semantic_category",
    "label",
    "text",
    "registered_authority_candidates",
    "scope",
    "reference_spans",
    "expected_suggestions",
    "annotation",
    "expected_suggestion_count",
    "confirmed_edge_legal_possible",
}
ALLOWED_LABELS = {"Depends", "Mentions only", "Contradicts or distinguishes", "Ambiguous", "No relationship"}
REQUIRED_CATEGORIES = {
    "explicit_reliance",
    "cross_sentence_reliance",
    "qualified_reliance",
    "alternative_independent_grounds",
    "quotation_without_adoption",
    "negation",
    "distinguishing_or_criticism",
    "multiple_authorities",
    "ambiguous_short_form",
    "alias_variation",
    "scope_lifecycle",
    "instruction_like_text",
}


class AdversarialCorpusIntegrityError(ValueError):
    """Raised when the locked challenge corpus cannot be trusted as labeled input."""


def canonical_manifest_sha256(manifest: dict[str, Any]) -> str:
    canonical = dict(manifest)
    canonical.pop("manifest_sha256", None)
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_adversarial_dependency_corpus(path: Path | str) -> dict[str, Any]:
    corpus_path = Path(path)
    manifest = cast(dict[str, Any], json.loads(corpus_path.read_text(encoding="utf-8")))
    if manifest.get("schema") != CHALLENGE_SCHEMA:
        raise AdversarialCorpusIntegrityError("unsupported adversarial dependency challenge schema")
    expected_hash = manifest.get("manifest_sha256")
    if not isinstance(expected_hash, str) or expected_hash != canonical_manifest_sha256(manifest):
        raise AdversarialCorpusIntegrityError("adversarial dependency challenge manifest hash mismatch")
    if manifest.get("status") != "locked-after-challenge-lock-commit":
        raise AdversarialCorpusIntegrityError("adversarial dependency challenge corpus is not locked")
    _validate_items(cast(list[Any], manifest.get("items")))
    _validate_mutations(cast(list[Any], manifest.get("mutations")), cast(list[dict[str, Any]], manifest["items"]))
    return manifest


def corpus_summary(manifest: dict[str, Any]) -> dict[str, int]:
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
        "mutations": len(cast(list[Any], manifest["mutations"])),
    }


def resolve_declared_span(text: str, span: dict[str, Any]) -> tuple[int, int]:
    value = span.get("text")
    occurrence = span.get("occurrence", 0)
    if not isinstance(value, str) or not value or not isinstance(occurrence, int) or occurrence < 0:
        raise AdversarialCorpusIntegrityError("declared span requires non-empty text and non-negative occurrence")
    start = -1
    position = 0
    for _ in range(occurrence + 1):
        start = text.find(value, position)
        if start < 0:
            raise AdversarialCorpusIntegrityError(f"declared span is absent from fixture text: {value!r}")
        position = start + len(value)
    return start, start + len(value)


def materialize_mutations(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    items = {str(item["id"]): item for item in cast(list[dict[str, Any]], manifest["items"])}
    variants: list[dict[str, Any]] = []
    for mutation in cast(list[dict[str, Any]], manifest["mutations"]):
        source = items[str(mutation["source_fixture_id"])]
        transformed = _transform(str(source["text"]), str(mutation["transformation"]))
        if transformed == source["text"]:
            raise AdversarialCorpusIntegrityError(f"mutation {mutation['id']} did not change its source text")
        variants.append(
            {
                "id": mutation["id"],
                "source_fixture_id": source["id"],
                "semantic_category": source["semantic_category"],
                "expected_suggestions": source["expected_suggestions"],
                "text": transformed,
                "seed": mutation["seed"],
                "transformation": mutation["transformation"],
            }
        )
    return variants


def _validate_items(items: list[Any]) -> None:
    if not isinstance(items, list) or len(items) < 80:
        raise AdversarialCorpusIntegrityError("challenge corpus requires at least 80 base fixtures")
    identifiers: set[str] = set()
    splits = {"development": 0, "holdout": 0}
    labels = {label: 0 for label in ALLOWED_LABELS}
    categories: set[str] = set()
    for raw_item in items:
        if not isinstance(raw_item, dict) or REQUIRED_FIELDS - raw_item.keys():
            raise AdversarialCorpusIntegrityError("each challenge fixture must provide all required fields")
        item = cast(dict[str, Any], raw_item)
        item_id = item["id"]
        if not isinstance(item_id, str) or not item_id or item_id in identifiers:
            raise AdversarialCorpusIntegrityError("challenge fixture IDs must be unique and non-empty")
        identifiers.add(item_id)
        split = item["split"]
        if split not in splits:
            raise AdversarialCorpusIntegrityError("challenge fixtures must be development or holdout")
        splits[split] += 1
        label = item["label"]
        if label not in ALLOWED_LABELS:
            raise AdversarialCorpusIntegrityError(f"fixture {item_id} has unsupported label")
        labels[label] += 1
        if not isinstance(item["text"], str) or not item["text"]:
            raise AdversarialCorpusIntegrityError(f"fixture {item_id} has no input text")
        if not isinstance(item["semantic_category"], str) or not item["semantic_category"]:
            raise AdversarialCorpusIntegrityError(f"fixture {item_id} lacks a semantic category")
        categories.add(item["semantic_category"])
        _validate_scope(item_id, item["scope"])
        candidates = item["registered_authority_candidates"]
        if not isinstance(candidates, list) or not all(isinstance(value, str) for value in candidates):
            raise AdversarialCorpusIntegrityError(f"fixture {item_id} has invalid authority candidates")
        _validate_spans(item_id, item, set(candidates))
    if splits["development"] < 32 or splits["holdout"] < 48:
        raise AdversarialCorpusIntegrityError(
            "challenge corpus requires at least 32 development and 48 holdout fixtures"
        )
    if labels["Depends"] < 24:
        raise AdversarialCorpusIntegrityError("challenge corpus requires at least 24 true dependencies")
    hard_negative_count = labels["Mentions only"] + labels["Contradicts or distinguishes"] + labels["No relationship"]
    if hard_negative_count < 32 or labels["Ambiguous"] < 16:
        raise AdversarialCorpusIntegrityError("challenge corpus lacks required hard-negative or ambiguous fixtures")
    if not REQUIRED_CATEGORIES <= categories:
        missing = ", ".join(sorted(REQUIRED_CATEGORIES - categories))
        raise AdversarialCorpusIntegrityError(f"challenge corpus lacks required semantic categories: {missing}")


def _validate_scope(item_id: str, scope: Any) -> None:
    if not isinstance(scope, dict) or not isinstance(scope.get("tenant_id"), str) or not scope["tenant_id"]:
        raise AdversarialCorpusIntegrityError(f"fixture {item_id} lacks tenant scope")
    for key in ("matter_id", "client_id"):
        if key in scope and not isinstance(scope[key], str):
            raise AdversarialCorpusIntegrityError(f"fixture {item_id} has invalid {key}")


def _validate_spans(item_id: str, item: dict[str, Any], candidates: set[str]) -> None:
    text = cast(str, item["text"])
    references = item["reference_spans"]
    suggestions = item["expected_suggestions"]
    if not isinstance(references, list) or not isinstance(suggestions, list):
        raise AdversarialCorpusIntegrityError(f"fixture {item_id} has invalid span labels")
    for reference in references:
        if not isinstance(reference, dict) or reference.get("target_id") not in candidates:
            raise AdversarialCorpusIntegrityError(f"fixture {item_id} has an unregistered reference target")
        resolve_declared_span(text, reference)
    for suggestion in suggestions:
        if not isinstance(suggestion, dict) or suggestion.get("target_id") not in candidates:
            raise AdversarialCorpusIntegrityError(f"fixture {item_id} has an unregistered suggestion target")
        for key in ("source_span", "target_span"):
            value = suggestion.get(key)
            if not isinstance(value, str) or not value or value not in text:
                raise AdversarialCorpusIntegrityError(f"fixture {item_id} has an invalid {key}")
    if item["expected_suggestion_count"] != len(suggestions):
        raise AdversarialCorpusIntegrityError(f"fixture {item_id} expected suggestion count does not match labels")
    if item["label"] == "Depends" and not suggestions:
        raise AdversarialCorpusIntegrityError(f"dependency fixture {item_id} lacks expected suggestion")
    if item["label"] != "Depends" and suggestions:
        raise AdversarialCorpusIntegrityError(f"non-dependency fixture {item_id} has an expected suggestion")


def _validate_mutations(mutations: list[Any], items: list[dict[str, Any]]) -> None:
    if not isinstance(mutations, list) or len(mutations) < 12:
        raise AdversarialCorpusIntegrityError("challenge corpus requires at least 12 fixed mutations")
    item_ids = {str(item["id"]) for item in items}
    mutation_ids: set[str] = set()
    transformations: set[str] = set()
    for raw_mutation in mutations:
        if not isinstance(raw_mutation, dict):
            raise AdversarialCorpusIntegrityError("mutation must be an object")
        mutation_id = raw_mutation.get("id")
        source_id = raw_mutation.get("source_fixture_id")
        transformation = raw_mutation.get("transformation")
        if not isinstance(mutation_id, str) or mutation_id in mutation_ids or source_id not in item_ids:
            raise AdversarialCorpusIntegrityError("mutation IDs and sources must be valid")
        if not isinstance(transformation, str) or transformation not in _TRANSFORMS:
            raise AdversarialCorpusIntegrityError("mutation transformation is unsupported")
        if not isinstance(raw_mutation.get("seed"), int) or not isinstance(raw_mutation.get("rationale"), str):
            raise AdversarialCorpusIntegrityError("mutation requires fixed seed and rationale")
        mutation_ids.add(mutation_id)
        transformations.add(transformation)
    if transformations != set(_TRANSFORMS):
        raise AdversarialCorpusIntegrityError("mutation manifest must cover every declared transformation")


def _transform(text: str, transformation: str) -> str:
    return _TRANSFORMS[transformation](text)


def _expand_whitespace(text: str) -> str:
    return text.replace(" ", "  ")


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _line_wrap(text: str) -> str:
    midpoint = text.find(" ", max(1, len(text) // 2))
    return text[:midpoint] + "\n" + text[midpoint + 1 :] if midpoint > 0 else text + "\n"


def _quote_conversion(text: str) -> str:
    return text.replace("“", '"').replace("”", '"').replace("'", "’")


def _punctuation_variation(text: str) -> str:
    return text[:-1] + ";" if text.endswith(".") else text + ";"


def _heading_insertion(text: str) -> str:
    return "Analysis\n\n" + text


def _footnote_relocation(text: str) -> str:
    return text.replace("(footnote: see archived schedule)", "[1]") + "\n[1] see archived schedule"


def _case_variation(text: str) -> str:
    return text.swapcase()


def _section_symbol_variation(text: str) -> str:
    return text.replace(" s. ", " § ").replace(" section ", " § ")


def _parenthetical_formatting(text: str) -> str:
    return text.replace("(", "[").replace(")", "]")


def _paragraph_boundary(text: str) -> str:
    return text.replace(". ", ".\n\n", 1)


def _declared_alias_substitution(text: str) -> str:
    return text.replace("Aster Reg. 7 s. 4", "Aster Regulation 7 section 4")


_TRANSFORMS = {
    "whitespace_expand": _expand_whitespace,
    "whitespace_collapse": _collapse_whitespace,
    "line_wrap": _line_wrap,
    "smart_straight_quotes": _quote_conversion,
    "punctuation_variation": _punctuation_variation,
    "heading_insertion": _heading_insertion,
    "footnote_relocation": _footnote_relocation,
    "case_variation": _case_variation,
    "section_symbol_variation": _section_symbol_variation,
    "parenthetical_formatting": _parenthetical_formatting,
    "paragraph_boundary": _paragraph_boundary,
    "declared_alias_substitution": _declared_alias_substitution,
}
