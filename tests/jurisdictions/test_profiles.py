# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from solomon.boundary.engine.client import BoundaryClient
from solomon.boundary.engine.jurisdictions import MINIMUM_PROFILE_DETECTOR_FAMILIES, profile_detector_families

MINIMUM_CASES = {
    "alice@example.com": "email",
    "passport number E1234567": "passport_number",
    "card 4111 1111 1111 1111": "credit_card",
    "confidential Q1 guidance": "mnpi_or_high_risk_secret",
}


def test_jurisdiction_profiles_strictly_extend_minimum_detector_families() -> None:
    for code in ("SG", "MY", "UK", "EU"):
        assert MINIMUM_PROFILE_DETECTOR_FAMILIES < profile_detector_families(code)


def test_jurisdiction_profile_rejects_unsupported_code() -> None:
    with pytest.raises(ValueError, match="jurisdiction profile must be one of"):
        profile_detector_families("ID")


@given(text=st.sampled_from(tuple(MINIMUM_CASES)))
def test_jurisdiction_profiles_preserve_minimum_findings(text: str) -> None:
    expected_kind = MINIMUM_CASES[text]
    client = BoundaryClient()

    for code in ("SG", "MY", "UK", "EU"):
        response = client.review(
            request={"text": text, "source_jurisdiction": code, "destination_jurisdiction": code}
        )
        assert expected_kind in {finding.kind for finding in response.findings}
