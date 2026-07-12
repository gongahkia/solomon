# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from solomon.boundary.engine.client import BoundaryClient


def test_uk_identifiers_are_detected_when_a_review_route_includes_uk() -> None:
    response = BoundaryClient().review(
        request={
            "text": (
                "NI AB 12 34 56 C; UTR 1234567890; Companies House number 01234567; "
                "NHS number 943 476 5919."
            ),
            "source_jurisdiction": "UK",
            "destination_jurisdiction": "EU",
        }
    )

    kinds = {finding.kind for finding in response.findings}

    assert response.classification == "HIGH_RISK"
    assert {
        "uk_national_insurance_number",
        "uk_utr",
        "uk_companies_house_number",
        "uk_nhs_number",
    }.issubset(kinds)
    assert all(finding.jurisdiction == "UK" for finding in response.findings if finding.kind.startswith("uk_"))


def test_uk_nhs_detection_rejects_an_invalid_check_digit() -> None:
    response = BoundaryClient().review(
        request={
            "text": "NHS number 943 476 5918.",
            "source_jurisdiction": "UK",
            "destination_jurisdiction": "EU",
        }
    )

    assert "uk_nhs_number" not in {finding.kind for finding in response.findings}


def test_uk_identifiers_are_pseudonymized() -> None:
    response = BoundaryClient().pseudonymize("UTR 1234567890 and NHS number 943 476 5919")

    assert "1234567890" not in response.pseudonymized_text
    assert "943 476 5919" not in response.pseudonymized_text
    assert {entry.entity_type for entry in response.mapping} == {"UK_UTR", "UK_NHS"}
