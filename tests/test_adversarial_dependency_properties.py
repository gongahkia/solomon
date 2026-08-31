# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from solomon.adversarial_corpus import load_adversarial_dependency_corpus
from solomon.boundary.solomon import SolomonBoundary
from solomon.graph.suggestions import (
    DependencySuggestion,
    ReferenceExtraction,
    extract_defined_terms_and_citations,
    suggest_authority_dependencies,
)

CORPUS = Path("examples/scenarios/adversarial-dependency-generalization-proof/corpus/manifest.json")
DEVELOPMENT_TEXTS = tuple(
    item["text"] for item in load_adversarial_dependency_corpus(CORPUS)["items"] if item["split"] == "development"
)


@settings(max_examples=16, deadline=None)
@given(text=st.sampled_from(DEVELOPMENT_TEXTS), padding=st.sampled_from(("", " ", "\n")))
def test_development_parser_spans_and_suggestions_are_repeatable_under_boundary_padding(
    text: str, padding: str
) -> None:
    content = padding + text
    first_references = extract_defined_terms_and_citations(content=content)
    second_references = extract_defined_terms_and_citations(content=content)
    first_suggestions = suggest_authority_dependencies(
        item_id="property-item", content=content, boundary=SolomonBoundary()
    )
    second_suggestions = suggest_authority_dependencies(
        item_id="property-item", content=content, boundary=SolomonBoundary()
    )

    assert _reference_projection(first_references) == _reference_projection(second_references)
    assert _suggestion_projection(first_suggestions) == _suggestion_projection(second_suggestions)
    for citation in first_references.citations:
        assert citation.span_start is not None and citation.span_end is not None
        assert content[citation.span_start : citation.span_end]
        if citation.metadata.get("grammar") in {"authority-section", "statute-section", "declared-alias"}:
            assert content[citation.span_start : citation.span_end] == citation.text
    for suggestion in first_suggestions:
        assert suggestion.source_span is not None and suggestion.authority_span is not None
        assert suggestion.source_span in content
        assert suggestion.authority_span in content


def _reference_projection(result: ReferenceExtraction) -> list[tuple[str, str, int | None, int | None]]:
    return [
        (citation.normalized_id, citation.text, citation.span_start, citation.span_end) for citation in result.citations
    ]


def _suggestion_projection(result: list[DependencySuggestion]) -> list[tuple[str, str | None, str | None, str | None]]:
    return [
        (
            suggestion.suggested_edge.target_id,
            suggestion.source_span,
            suggestion.authority_span,
            suggestion.fingerprint,
        )
        for suggestion in result
    ]
