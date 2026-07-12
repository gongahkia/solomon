# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest

from solomon.boundary.engine.client import BoundaryClient


def _cases() -> list[dict[str, object]]:
    return json.loads(Path(__file__).with_name("fixtures.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _cases(), ids=lambda case: str(case["jurisdiction"]))
def test_jurisdiction_fixture_is_detected(case: dict[str, object]) -> None:
    jurisdiction = str(case["jurisdiction"])
    response = BoundaryClient().review(
        request={
            "text": str(case["text"]),
            "source_jurisdiction": jurisdiction,
            "destination_jurisdiction": jurisdiction,
        }
    )

    kinds = {finding.kind for finding in response.findings}

    assert response.classification == "HIGH_RISK"
    assert set(case["expected_kinds"]).issubset(kinds)
