# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from solomon.boundary.engine.client import BoundaryClient


def test_my_mykad_and_ssm_registration_number_are_detected() -> None:
    response = BoundaryClient().review(
        request={
            "text": "MyKad 900101-14-1234; SSM registration number 201901000005.",
            "source_jurisdiction": "MY",
            "destination_jurisdiction": "SG",
        }
    )

    kinds = {finding.kind for finding in response.findings}

    assert response.classification == "HIGH_RISK"
    assert {"my_mykad", "my_ssm_registration_number"}.issubset(kinds)
    assert all(finding.jurisdiction == "MY" for finding in response.findings if finding.kind.startswith("my_"))


def test_my_identifiers_are_pseudonymized() -> None:
    response = BoundaryClient().pseudonymize("MyPR 900101141234 and registration no. 201901000005")

    assert "900101141234" not in response.pseudonymized_text
    assert "201901000005" not in response.pseudonymized_text
    assert {entry.entity_type for entry in response.mapping} == {"MY_MYKAD", "MY_SSM_REGISTRATION"}
