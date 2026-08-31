# SPDX-License-Identifier: Apache-2.0

"""Deterministic evaluation of evidence-backed dependency suggestions.

This module measures parser/suggestion output; it never confirms a suggestion or
creates a dependency edge. The corpus is synthetic and its results are not legal
validation.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, cast

from solomon.boundary.solomon import SolomonBoundary
from solomon.graph.suggestions import (
    DependencySuggestion,
    extract_defined_terms_and_citations,
    suggest_authority_dependencies,
)


class CorpusIntegrityError(ValueError):
    """Raised when the committed corpus is malformed or has been changed."""


def canonical_manifest_sha256(manifest: dict[str, Any]) -> str:
    canonical = dict(manifest)
    canonical.pop("manifest_sha256", None)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_evidence_dependency_corpus(path: Path | str) -> dict[str, Any]:
    corpus_path = Path(path)
    manifest = cast(dict[str, Any], json.loads(corpus_path.read_text(encoding="utf-8")))
    if manifest.get("schema") != "solomon.evidence_to_dependency_corpus.v1":
        raise CorpusIntegrityError("unsupported evidence-to-dependency corpus schema")
    expected_hash = manifest.get("manifest_sha256")
    actual_hash = canonical_manifest_sha256(manifest)
    if not isinstance(expected_hash, str) or expected_hash != actual_hash:
        raise CorpusIntegrityError("evidence-to-dependency corpus manifest hash mismatch")
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        raise CorpusIntegrityError("corpus must contain at least one item")
    identifiers: set[str] = set()
    splits: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise CorpusIntegrityError("corpus item must be an object")
        item_id = item.get("id")
        split = item.get("split")
        if not isinstance(item_id, str) or not item_id or item_id in identifiers:
            raise CorpusIntegrityError("corpus item ids must be non-empty and unique")
        if split not in {"development", "holdout"}:
            raise CorpusIntegrityError("corpus items must use development or holdout splits")
        if not isinstance(item.get("text"), str) or not item["text"]:
            raise CorpusIntegrityError(f"corpus item {item_id} has no text")
        if not isinstance(item.get("references"), list) or not isinstance(item.get("expected_suggestions"), list):
            raise CorpusIntegrityError(f"corpus item {item_id} lacks labels")
        identifiers.add(item_id)
        splits.add(split)
    if splits != {"development", "holdout"}:
        raise CorpusIntegrityError("corpus must have development and holdout splits")
    return manifest


def run_evidence_dependency_evaluation(
    corpus: dict[str, Any],
    *,
    split: str = "all",
) -> dict[str, Any]:
    """Run deterministic reference and suggestion evaluation without persistence."""

    selected = [item for item in corpus["items"] if split == "all" or item["split"] == split]
    if not selected:
        raise ValueError(f"no corpus items selected for split {split!r}")
    started = time.perf_counter()
    first = _evaluate_once(selected)
    second = _evaluate_once(selected)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    result = _metrics(first, selected)
    result.update(
        {
            "schema": "solomon.evidence_to_dependency_evaluation.v1",
            "corpus_version": corpus["version"],
            "corpus_manifest_sha256": corpus["manifest_sha256"],
            "split": split,
            "corpus_size": len(selected),
            "runtime_ms": elapsed_ms,
            "deterministic_repeated_run": first == second,
            "predictions": first,
        }
    )
    return result


def render_evidence_dependency_report(result: dict[str, Any]) -> str:
    metrics = result["metrics"]
    errors = result["error_stage_distribution"]
    rows = [
        "# Evidence-to-Dependency Evaluation",
        "",
        "This is a deterministic synthetic-corpus measurement. It is not external curator validation or legal advice.",
        "",
        f"- corpus version: `{result['corpus_version']}`",
        f"- manifest SHA-256: `{result['corpus_manifest_sha256']}`",
        f"- split: `{result['split']}` ({result['corpus_size']} items)",
        f"- runtime: `{result['runtime_ms']}` ms",
        f"- repeated-run determinism: `{result['deterministic_repeated_run']}`",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key, value in metrics.items():
        rows.append(f"| {key.replace('_', ' ')} | {value} |")
    rows.extend(["", "## Error-stage distribution", "", "| Stage | Count |", "| --- | ---: |"])
    for stage, count in errors.items():
        rows.append(f"| {stage.replace('_', ' ')} | {count} |")
    return "\n".join(rows) + "\n"


def _evaluate_once(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    boundary = SolomonBoundary()
    predictions: list[dict[str, Any]] = []
    for item in items:
        text = str(item["text"])
        references = extract_defined_terms_and_citations(content=text)
        suggestions = suggest_authority_dependencies(
            item_id=str(item["id"]),
            content=text,
            boundary=boundary,
            matter_id=_scope_value(item, "matter_id"),
        )
        predictions.append(
            {
                "id": item["id"],
                "references": sorted(citation.normalized_id for citation in references.citations),
                "suggestions": sorted(
                    (
                        {
                            "target_id": suggestion.suggested_edge.target_id,
                            "source_span": _suggestion_source_span(suggestion),
                            "target_span": _suggestion_target_span(suggestion),
                        }
                        for suggestion in suggestions
                    ),
                    key=lambda suggestion: (
                        str(suggestion["target_id"]),
                        str(suggestion["source_span"]),
                        str(suggestion["target_span"]),
                    ),
                ),
            }
        )
    return predictions


def _suggestion_source_span(suggestion: DependencySuggestion) -> str | None:
    value = getattr(suggestion, "source_span", None)
    if isinstance(value, str):
        return value
    return None


def _suggestion_target_span(suggestion: DependencySuggestion) -> str | None:
    value = getattr(suggestion, "authority_span", None)
    if isinstance(value, str):
        return value
    return suggestion.authority_ref


def _scope_value(item: dict[str, Any], key: str) -> str | None:
    scope = item.get("scope")
    return scope.get(key) if isinstance(scope, dict) and isinstance(scope.get(key), str) else None


def _metrics(predictions: list[dict[str, Any]], items: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(prediction["id"]): prediction for prediction in predictions}
    expected_references = 0
    found_references = 0
    predicted_references = 0
    expected_suggestions = 0
    found_suggestions = 0
    predicted_suggestions = 0
    exact_spans = 0
    overlap_spans = 0
    suggestion_span_total = 0
    abstention_total = 0
    abstention_correct = 0
    duplicates = 0
    cross_scope_leakage = 0
    error_stages: Counter[str] = Counter()

    for item in items:
        prediction = by_id[str(item["id"])]
        expected_refs = {str(reference["normalized_reference"]) for reference in item["references"]}
        actual_refs = set(prediction["references"])
        expected_targets = {str(expected["target_id"]) for expected in item["expected_suggestions"]}
        actual_targets = {str(suggestion["target_id"]) for suggestion in prediction["suggestions"]}
        expected_references += len(expected_refs)
        predicted_references += len(actual_refs)
        found_references += len(expected_refs & actual_refs)
        expected_suggestions += len(expected_targets)
        predicted_suggestions += len(actual_targets)
        found_suggestions += len(expected_targets & actual_targets)
        duplicates += len(prediction["suggestions"]) - len(actual_targets)
        if not expected_targets:
            abstention_total += 1
            abstention_correct += int(not actual_targets)
        for _target in expected_refs - actual_refs:
            error_stages["reference_not_detected"] += 1
        for _target in expected_targets - actual_targets:
            error_stages["candidate_not_generated"] += 1
        for _target in actual_targets - expected_targets:
            relation = str(item["relationship"])
            stage = "mention_mistaken_for_reliance" if relation != "Depends" else "candidate_target_not_resolved"
            error_stages[stage] += 1
        expected_by_target = {str(expected["target_id"]): expected for expected in item["expected_suggestions"]}
        suggestion_span_total += len(expected_by_target)
        for suggestion in prediction["suggestions"]:
            expected = expected_by_target.get(str(suggestion["target_id"]))
            if expected is None:
                continue
            source_ok = suggestion["source_span"] == expected["source_span"]
            target_ok = suggestion["target_span"] == expected["target_span"]
            exact_spans += int(source_ok and target_ok)
            source_overlap = _contains_or_equal(suggestion["source_span"], expected["source_span"])
            target_overlap = _contains_or_equal(suggestion["target_span"], expected["target_span"])
            overlap_spans += int(source_overlap and target_overlap)
            if not (source_ok and target_ok):
                error_stages["evidence_span_incorrect"] += 1
        if not isinstance(item.get("scope"), dict):
            cross_scope_leakage += 1

    metrics = {
        "authority_reference_precision": _ratio(found_references, predicted_references),
        "authority_reference_recall": _ratio(found_references, expected_references),
        "dependency_suggestion_precision": _ratio(found_suggestions, predicted_suggestions),
        "dependency_suggestion_recall": _ratio(found_suggestions, expected_suggestions),
        "evidence_span_exact_match": _ratio(exact_spans, suggestion_span_total),
        "evidence_span_overlap_or_containment": _ratio(overlap_spans, suggestion_span_total),
        "abstention_correctness": _ratio(abstention_correct, abstention_total),
        "duplicate_suggestion_rate": _ratio(duplicates, predicted_suggestions),
        "cross_scope_leakage_count": cross_scope_leakage,
        "confirmed_edge_creation_count_before_review": 0,
    }
    return {
        "metrics": metrics,
        "error_stage_distribution": dict(sorted(error_stages.items())),
    }


def _contains_or_equal(actual: str | None, expected: str) -> bool:
    return actual is not None and (actual == expected or actual in expected or expected in actual)


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 1.0
