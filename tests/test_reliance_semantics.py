# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Callable

from hypothesis import given, settings
from hypothesis import strategies as st

from solomon.reliance_semantics import analyze_reliance, authority_fingerprint, normalize_analysis


def test_normalized_analysis_is_idempotent_and_reconstructs_section_symbol_raw_span() -> None:
    raw = "Our analysis\nrelies   on “Aster Regulation 7 § 4” for release."
    analysis = normalize_analysis(raw)
    repeated = normalize_analysis(analysis.text)

    assert analysis.text == 'Our analysis relies on "Aster Regulation 7 section 4" for release.'
    assert repeated.text == analysis.text
    section_start = analysis.text.index("section")
    raw_start, raw_end = analysis.raw_span(section_start, section_start + len("section"))
    assert raw[raw_start:raw_end] == "§"
    assert authority_fingerprint("Aster Regulation 7 § 4") == "aster-regulation-7-section-4"


@settings(max_examples=24, deadline=None)
@given(spacing=st.sampled_from((" ", "  ", "\n", "\n\n", "\t")))
def test_whitespace_normalization_preserves_raw_authority_and_evidence_slices(spacing: str) -> None:
    raw = f"This advice relies{spacing}on Atlas Regulation 12 section 4 for release."
    _, _, candidates = analyze_reliance(raw, registered_authority_ids=["atlas-regulation-12-section-4"])

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.authority_text == "Atlas Regulation 12 section 4"
    assert candidate.source_text == raw
    assert raw[candidate.authority_start : candidate.authority_end] == candidate.authority_text
    assert raw[candidate.source_start : candidate.source_end] == candidate.source_text


@settings(max_examples=12, deadline=None)
@given(case=st.sampled_from((str.lower, str.upper, str.swapcase)))
def test_case_projection_changes_no_authority_fingerprint_or_target(case: Callable[[str], str]) -> None:
    transform = case
    raw = transform("We rely on Aster Regulation 7 section 4 for release.")
    _, _, candidates = analyze_reliance(raw, registered_authority_ids=["aster-regulation-7-section-4"])

    assert [candidate.target_id for candidate in candidates] == ["aster-regulation-7-section-4"]
    assert candidates[0].authority_text in raw


def test_smart_quotes_and_wrapped_whitespace_do_not_use_normalized_text_as_evidence() -> None:
    raw = "This advice\nrelies on Hazel Code 5 § 3 for the “release date”."
    _, _, candidates = analyze_reliance(raw, registered_authority_ids=["hazel-code-5-section-3"])

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source_text == raw
    assert candidate.authority_text == "Hazel Code 5 § 3"
    assert "§" in candidate.authority_text
    assert "normalized-analysis pattern=direct-relies-on" in candidate.explanation
    assert "guards=attribution:clear" in candidate.explanation


def test_local_negation_attribution_and_quotation_fail_closed() -> None:
    cases = (
        "We do not rely on Aster Regulation 7 section 4.",
        "The counterparty relies on Aster Regulation 7 section 4.",
        "The witness wrote, “we rely on Aster Regulation 7 section 4.”",
        "Draft a note that relies on Aster Regulation 7 section 4 if counsel approves.",
    )
    for raw in cases:
        _, _, candidates = analyze_reliance(raw, registered_authority_ids=["aster-regulation-7-section-4"])

        assert candidates == []


def test_adjacent_cross_sentence_window_is_bounded_and_reversible() -> None:
    raw = "This advice adopts the approach in Indigo Act 6 section 3. That authority supplies the filing deadline."
    _, _, candidates = analyze_reliance(raw, registered_authority_ids=["indigo-act-6-section-3"])

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source_text == raw
    assert candidate.authority_text == "Indigo Act 6 section 3"
    assert "pattern=cross-sentence-adoption" in candidate.explanation
    assert "window=previous+current" in candidate.explanation


def test_reference_not_in_registered_scope_cannot_become_a_candidate() -> None:
    _, references, candidates = analyze_reliance(
        "We rely on Atlas Regulation 12 section 4 for release.", registered_authority_ids=[]
    )

    assert [reference.normalized_id for reference in references] == ["atlas-regulation-12-section-4"]
    assert candidates == []


def test_raw_mapping_rejects_invalid_intervals() -> None:
    analysis = normalize_analysis("Aster Regulation 7 section 4")

    for start, end in ((-1, 1), (1, 1), (0, len(analysis.text) + 1)):
        try:
            analysis.raw_span(start, end)
        except ValueError:
            continue
        raise AssertionError("invalid analysis interval did not fail closed")
