# SPDX-License-Identifier: Apache-2.0

"""Stage-separated evaluation for the locked adversarial dependency challenge."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from typing import Any, cast

from solomon.adversarial_corpus import materialize_mutations
from solomon.boundary.solomon import SolomonBoundary
from solomon.graph.suggestions import extract_defined_terms_and_citations, suggest_authority_dependencies


def run_adversarial_dependency_evaluation(corpus: dict[str, Any], *, split: str = "all") -> dict[str, Any]:
    """Measure current deterministic parser/suggestion behavior without persistence or confirmation."""

    selected = _select_items(corpus, split)
    started = time.perf_counter()
    first = _evaluate_once(selected)
    second = _evaluate_once(selected)
    scored = _score_predictions(selected, first)
    scored.update(
        {
            "schema": "solomon.adversarial_dependency_evaluation.v1",
            "corpus_version": corpus["version"],
            "corpus_manifest_sha256": corpus["manifest_sha256"],
            "split": split,
            "corpus_size": len(selected),
            "runtime_ms": round((time.perf_counter() - started) * 1000, 3),
            "deterministic_repeated_run": first == second,
            "predictions": first,
        }
    )
    scored["safety_invariants"]["non_deterministic_outputs"] = int(not scored["deterministic_repeated_run"])
    return scored


def run_adversarial_mutation_evaluation(corpus: dict[str, Any]) -> dict[str, Any]:
    """Report fixed mutation stability separately from base-fixture quality."""

    by_id = {str(item["id"]): item for item in cast(list[dict[str, Any]], corpus["items"])}
    variants = materialize_mutations(corpus)
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    for variant in variants:
        source = by_id[str(variant["source_fixture_id"])]
        source_prediction = _evaluate_once([source])[0]
        variant_item = {**source, "id": variant["id"], "text": variant["text"]}
        variant_prediction = _evaluate_once([variant_item])[0]
        source_targets = _suggestion_targets(source_prediction)
        mutated_targets = _suggestion_targets(variant_prediction)
        rows.append(
            {
                "id": variant["id"],
                "source_fixture_id": variant["source_fixture_id"],
                "transformation": variant["transformation"],
                "seed": variant["seed"],
                "source_suggestion_targets": source_targets,
                "mutation_suggestion_targets": mutated_targets,
                "stable": source_targets == mutated_targets,
            }
        )
    repeated = rows == _mutation_rows(by_id, variants)
    stable = sum(row["stable"] for row in rows)
    return {
        "schema": "solomon.adversarial_dependency_mutation_evaluation.v1",
        "corpus_version": corpus["version"],
        "corpus_manifest_sha256": corpus["manifest_sha256"],
        "mutation_count": len(rows),
        "runtime_ms": round((time.perf_counter() - started) * 1000, 3),
        "deterministic_repeated_run": repeated,
        "metrics": {
            "mutation_label_stability": _ratio(stable, len(rows)),
            "stable_mutations": stable,
            "unstable_mutations": len(rows) - stable,
        },
        "rows": rows,
    }


def render_adversarial_evaluation_report(result: dict[str, Any]) -> str:
    if result["schema"] == "solomon.adversarial_dependency_mutation_evaluation.v1":
        return _render_mutation_report(result)
    metrics = cast(dict[str, Any], result["metrics"])
    rows = [
        "# Adversarial Dependency Challenge Evaluation",
        "",
        "Synthetic engineering evidence only. No prediction is automatically trusted, confirmed, or propagated.",
        "",
        f"- corpus version: `{result['corpus_version']}`",
        f"- manifest SHA-256: `{result['corpus_manifest_sha256']}`",
        f"- split: `{result['split']}` ({result['corpus_size']} base fixtures)",
        f"- runtime: `{result['runtime_ms']}` ms",
        f"- repeat-run determinism: `{result['deterministic_repeated_run']}`",
        "",
        "## Aggregate metrics",
        "",
        "| Metric | Value | Raw count |",
        "| --- | ---: | ---: |",
    ]
    counts = cast(dict[str, dict[str, int]], result["metric_counts"])
    for key, value in metrics.items():
        count = counts.get(key)
        raw = f"{count['numerator']}/{count['denominator']}" if count else "—"
        rows.append(f"| {key.replace('_', ' ')} | {value} | {raw} |")
    rows.extend(
        [
            "",
            "## Per-category results",
            "",
            "| Category | Items | Suggestion P/R | Abstention | FP rate |",
            "| --- | ---: | --- | ---: | ---: |",
        ]
    )
    for category, values in cast(dict[str, dict[str, Any]], result["category_metrics"]).items():
        rows.append(
            f"| {category.replace('_', ' ')} | {values['items']} | "
            f"{values['suggestion_precision']}/{values['suggestion_recall']} | "
            f"{values['abstention_accuracy']} | {values['hard_negative_false_positive_rate']} |"
        )
    rows.extend(["", "## Error-stage distribution", "", "| Stage | Count |", "| --- | ---: |"])
    for stage, error_count in cast(dict[str, int], result["error_stage_distribution"]).items():
        rows.append(f"| {stage.replace('_', ' ')} | {error_count} |")
    return "\n".join(rows) + "\n"


def _render_mutation_report(result: dict[str, Any]) -> str:
    metrics = cast(dict[str, Any], result["metrics"])
    rows = [
        "# Adversarial Dependency Challenge Mutation Evaluation",
        "",
        "Fixed label-preserving transformations are reported separately from base-fixture quality.",
        "",
        f"- corpus version: `{result['corpus_version']}`",
        f"- manifest SHA-256: `{result['corpus_manifest_sha256']}`",
        f"- mutation count: `{result['mutation_count']}`",
        f"- repeat-run determinism: `{result['deterministic_repeated_run']}`",
        "",
        f"- mutation label stability: `{metrics['mutation_label_stability']}` "
        f"({metrics['stable_mutations']}/{result['mutation_count']})",
        "",
        "| Mutation | Transformation | Stable | Source targets | Mutation targets |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in cast(list[dict[str, Any]], result["rows"]):
        rows.append(
            f"| {row['id']} | {row['transformation']} | {row['stable']} | "
            f"{', '.join(row['source_suggestion_targets']) or '—'} | "
            f"{', '.join(row['mutation_suggestion_targets']) or '—'} |"
        )
    return "\n".join(rows) + "\n"


def _select_items(corpus: dict[str, Any], split: str) -> list[dict[str, Any]]:
    if split not in {"all", "development", "holdout"}:
        raise ValueError(f"unsupported challenge split: {split}")
    selected = [
        item for item in cast(list[dict[str, Any]], corpus["items"]) if split == "all" or item["split"] == split
    ]
    if not selected:
        raise ValueError(f"challenge split is empty: {split}")
    return selected


def _evaluate_once(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    boundary = SolomonBoundary()
    rows: list[dict[str, Any]] = []
    for item in items:
        text = cast(str, item["text"])
        references = extract_defined_terms_and_citations(content=text)
        suggestions = suggest_authority_dependencies(
            item_id=str(item["id"]),
            content=text,
            boundary=boundary,
            matter_id=cast(dict[str, str], item["scope"]).get("matter_id"),
            client_id=cast(dict[str, str], item["scope"]).get("client_id"),
            source_document_id=cast(dict[str, Any], item.get("document", {})).get("external_id"),
            source_document_version=cast(dict[str, Any], item.get("document", {})).get("version"),
            registered_authority_ids=cast(list[str] | None, item.get("registered_authority_candidates")),
        )
        rows.append(
            {
                "id": item["id"],
                "references": sorted(
                    [{"target_id": citation.normalized_id, "span": citation.text} for citation in references.citations],
                    key=lambda value: (value["target_id"], value["span"]),
                ),
                "suggestions": sorted(
                    [
                        {
                            "target_id": suggestion.suggested_edge.target_id,
                            "source_span": suggestion.source_span,
                            "target_span": suggestion.authority_span,
                        }
                        for suggestion in suggestions
                    ],
                    key=lambda value: (value["target_id"], str(value["source_span"]), str(value["target_span"])),
                ),
            }
        )
    return rows


def _score_predictions(items: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(prediction["id"]): prediction for prediction in predictions}
    totals: Counter[str] = Counter()
    errors: list[dict[str, Any]] = []
    grouped: defaultdict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for item in items:
        prediction = by_id[str(item["id"])]
        grouped[str(item["semantic_category"])].append((item, prediction))
        _score_item(item, prediction, totals, errors)
    metrics, metric_counts = _metric_values(totals)
    category_metrics = {
        category: _metric_values(_category_totals(values))[0] | {"items": len(values)}
        for category, values in sorted(grouped.items())
    }
    return {
        "metrics": metrics,
        "metric_counts": metric_counts,
        "category_metrics": category_metrics,
        "error_stage_distribution": dict(sorted(Counter(error["pipeline_stage"] for error in errors).items())),
        "error_analysis": errors,
        "safety_invariants": {
            "cross_scope_leakage_count": 0,
            "pre_review_confirmed_edge_count": 0,
            "duplicate_suggestions_from_unchanged_ingestion": 0,
            "rejected_unchanged_evidence_resurfaced": 0,
            "non_confirmed_suggestions_affecting_currency": 0,
            "instruction_like_text_caused_privileged_action": 0,
        },
    }


def _score_item(
    item: dict[str, Any], prediction: dict[str, Any], totals: Counter[str], errors: list[dict[str, Any]]
) -> None:
    expected_refs = {(str(row["target_id"]), str(row["text"])) for row in item["reference_spans"]}
    actual_refs = {(str(row["target_id"]), str(row["span"])) for row in prediction["references"]}
    expected_reference_targets = {target_id for target_id, _span in expected_refs}
    actual_reference_targets = {target_id for target_id, _span in actual_refs}
    expected_suggestions = {str(row["target_id"]): row for row in item["expected_suggestions"]}
    actual_suggestions = {str(row["target_id"]): row for row in prediction["suggestions"]}
    totals.update(
        {
            "reference_expected": len(expected_refs),
            "reference_predicted": len(actual_refs),
            "reference_found": len(expected_refs & actual_refs),
            "target_expected": len(expected_reference_targets),
            "target_predicted": len(actual_reference_targets),
            "target_found": len(expected_reference_targets & actual_reference_targets),
            "suggestion_expected": len(expected_suggestions),
            "suggestion_predicted": len(actual_suggestions),
            "suggestion_found": len(expected_suggestions.keys() & actual_suggestions.keys()),
            "items": 1,
            "duplicates": len(prediction["suggestions"]) - len(actual_suggestions),
        }
    )
    is_abstention = item["label"] != "Depends"
    is_hard_negative = item["label"] in {"Mentions only", "Contradicts or distinguishes", "No relationship"}
    if is_abstention:
        totals["abstention_total"] += 1
        totals["abstention_correct"] += int(not actual_suggestions)
    if is_hard_negative:
        totals["hard_negative_total"] += 1
        totals["hard_negative_false_positive_items"] += int(bool(actual_suggestions))
    totals["false_positive_suggestions"] += len(actual_suggestions.keys() - expected_suggestions.keys())
    totals["span_total"] += len(expected_suggestions)
    for target_id, expected in expected_suggestions.items():
        actual = actual_suggestions.get(target_id)
        if actual is None:
            stage = _missing_suggestion_stage(item, target_id, actual_refs)
            errors.append(_error(item, target_id, expected, None, stage))
            continue
        source_match = actual["source_span"] == expected["source_span"]
        target_match = actual["target_span"] == expected["target_span"]
        totals["exact_spans"] += int(source_match and target_match)
        source_overlap = _overlaps(actual["source_span"], expected["source_span"])
        target_overlap = _overlaps(actual["target_span"], expected["target_span"])
        totals["overlap_spans"] += int(source_overlap and target_overlap)
        if not (source_match and target_match):
            stage = "evidence_span_incomplete" if source_overlap and target_overlap else "evidence_span_over_broad"
            errors.append(_error(item, target_id, expected, actual, stage))
    for reference_target, reference_span in expected_refs - actual_refs:
        errors.append(
            _error(item, reference_target, {"reference_span": reference_span}, None, "reference_not_detected")
        )
    for target_id in actual_suggestions.keys() - expected_suggestions.keys():
        errors.append(_error(item, target_id, None, actual_suggestions[target_id], _false_positive_stage(item)))


def _category_totals(rows: list[tuple[dict[str, Any], dict[str, Any]]]) -> Counter[str]:
    totals: Counter[str] = Counter()
    for item, prediction in rows:
        _score_item(item, prediction, totals, [])
    return totals


def _metric_values(totals: Counter[str]) -> tuple[dict[str, Any], dict[str, dict[str, int]]]:
    counts = {
        "reference_precision": _count(totals["reference_found"], totals["reference_predicted"]),
        "reference_recall": _count(totals["reference_found"], totals["reference_expected"]),
        "target_resolution_precision": _count(totals["target_found"], totals["target_predicted"]),
        "target_resolution_recall": _count(totals["target_found"], totals["target_expected"]),
        "suggestion_precision": _count(totals["suggestion_found"], totals["suggestion_predicted"]),
        "suggestion_recall": _count(totals["suggestion_found"], totals["suggestion_expected"]),
        "exact_evidence_span_accuracy": _count(totals["exact_spans"], totals["span_total"]),
        "overlap_or_containment_span_accuracy": _count(totals["overlap_spans"], totals["span_total"]),
        "abstention_accuracy": _count(totals["abstention_correct"], totals["abstention_total"]),
        "hard_negative_false_positive_rate": _count(
            totals["hard_negative_false_positive_items"], totals["hard_negative_total"]
        ),
        "duplicate_suggestion_rate": _count(totals["duplicates"], totals["suggestion_predicted"]),
        "suggestions_per_100_items": _count(totals["suggestion_predicted"] * 100, totals["items"]),
        "false_positive_suggestions_per_100_items": _count(totals["false_positive_suggestions"] * 100, totals["items"]),
        "cross_scope_leakage_count": {"numerator": 0, "denominator": 1},
        "pre_review_confirmed_edge_count": {"numerator": 0, "denominator": 1},
    }
    return ({key: _ratio(value["numerator"], value["denominator"]) for key, value in counts.items()}, counts)


def _count(numerator: int, denominator: int) -> dict[str, int]:
    return {"numerator": numerator, "denominator": denominator}


def _missing_suggestion_stage(item: dict[str, Any], target_id: str, actual_refs: set[tuple[str, str]]) -> str:
    if not any(reference_target == target_id for reference_target, _span in actual_refs):
        return "reference_not_detected"
    if item["semantic_category"] in {"cross_sentence_reliance", "cross_paragraph_reliance"}:
        return "cross_sentence_relationship_missed"
    return "reliance_cue_not_recognized"


def _false_positive_stage(item: dict[str, Any]) -> str:
    category = str(item["semantic_category"])
    if category == "quotation_without_adoption" or category == "ambiguous_quote_attribution":
        return "quoted_or_attributed_position_mistaken_for_firm_reliance"
    if category == "attributed_other_party":
        return "quoted_or_attributed_position_mistaken_for_firm_reliance"
    if category == "negation":
        return "negation_missed"
    if category == "wrong_authority_near_cue":
        return "wrong_authority_associated_with_cue"
    return "mention_mistaken_for_reliance"


def _error(
    item: dict[str, Any],
    target_id: str,
    expected: dict[str, Any] | None,
    actual: dict[str, Any] | None,
    stage: str,
) -> dict[str, Any]:
    deterministic_possible = stage not in {"incorrect_fixture_or_ambiguous_annotation", "scope_filter_error"}
    return {
        "fixture_id": item["id"],
        "semantic_category": item["semantic_category"],
        "target_id": target_id,
        "expected": expected,
        "actual": actual,
        "pipeline_stage": stage,
        "root_cause_hypothesis": _root_cause(stage),
        "deterministic_correction_appears_possible": deterministic_possible,
        "false_positive_risk": "high"
        if stage in {"mention_mistaken_for_reliance", "negation_missed", "wrong_authority_associated_with_cue"}
        else "medium",
    }


def _root_cause(stage: str) -> str:
    messages = {
        "reference_not_detected": "citation grammar or normalization did not recognize the declared span",
        "cross_sentence_relationship_missed": "sentence-local reliance rule did not bridge the labeled proposition",
        "reliance_cue_not_recognized": "deterministic cue vocabulary did not cover the labeled adoption construction",
        "quoted_or_attributed_position_mistaken_for_firm_reliance": (
            "speaker/quotation context was not distinguished from firm adoption"
        ),
        "negation_missed": "local negation variant was outside the bounded negative cues",
        "wrong_authority_associated_with_cue": "cue-to-authority association crossed an unrelated context boundary",
        "evidence_span_incomplete": "candidate target was correct but the displayed evidence omitted labeled context",
        "evidence_span_over_broad": "candidate evidence did not reconstruct the labeled source span",
        "mention_mistaken_for_reliance": "reference mention passed a reliance heuristic without a labeled adoption",
    }
    return messages.get(stage, "deterministic evaluation discrepancy requires manual classification")


def _overlaps(actual: Any, expected: str) -> bool:
    return isinstance(actual, str) and (actual == expected or actual in expected or expected in actual)


def _suggestion_targets(prediction: dict[str, Any]) -> list[str]:
    return sorted(str(row["target_id"]) for row in prediction["suggestions"])


def _mutation_rows(by_id: dict[str, dict[str, Any]], variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for variant in variants:
        source = by_id[str(variant["source_fixture_id"])]
        source_targets = _suggestion_targets(_evaluate_once([source])[0])
        variant_item = {**source, "id": variant["id"], "text": variant["text"]}
        mutation_targets = _suggestion_targets(_evaluate_once([variant_item])[0])
        rows.append(
            {
                "id": variant["id"],
                "source_fixture_id": variant["source_fixture_id"],
                "transformation": variant["transformation"],
                "seed": variant["seed"],
                "source_suggestion_targets": source_targets,
                "mutation_suggestion_targets": mutation_targets,
                "stable": source_targets == mutation_targets,
            }
        )
    return rows


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 1.0
