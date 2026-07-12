# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from solomon.boundary.engine.client import BoundaryClient


@pytest.mark.parametrize(
    ("jurisdiction", "term"),
    [
        ("SG", "SFA section 218"),
        ("MY", "CMSA sections 188-189"),
        ("UK", "UK MAR"),
        ("EU", "MAR Article 7"),
    ],
)
def test_jurisdictional_market_abuse_terms_are_mnpi(jurisdiction: str, term: str) -> None:
    response = BoundaryClient().review(
        request={"text": term, "source_jurisdiction": jurisdiction, "destination_jurisdiction": jurisdiction}
    )

    finding = next(finding for finding in response.findings if finding.kind == "jurisdiction_strict_term")

    assert finding.severity == "high"
    assert finding.metadata["category"] == "MNPI"
