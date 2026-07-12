# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from solomon.boundary.engine.client import BoundaryClient


def test_sg_identifiers_and_myinfo_field_are_detected() -> None:
    response = BoundaryClient().review(
        request={
            "text": "UEN 200312345A; UEN T08FC1234A; ASGD A1234567D; Myinfo uinfin; M1234567A.",
            "source_jurisdiction": "SG",
            "destination_jurisdiction": "EU",
        }
    )

    kinds = {finding.kind for finding in response.findings}

    assert response.classification == "HIGH_RISK"
    assert {"sg_uen", "sg_iras_tax_reference", "sg_myinfo_field", "national_id"}.issubset(kinds)
    assert all(finding.jurisdiction == "SG" for finding in response.findings if finding.kind.startswith("sg_"))


def test_sg_uens_and_iras_tax_references_are_pseudonymized() -> None:
    response = BoundaryClient().pseudonymize("UEN 200312345A; ASGD A1234567D")

    assert "200312345A" not in response.pseudonymized_text
    assert "A1234567D" not in response.pseudonymized_text
    assert {entry.entity_type for entry in response.mapping} == {"SG_UEN", "SG_IRAS_TAX_REFERENCE"}
