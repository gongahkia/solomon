# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from solomon.boundary.engine.client import BoundaryClient


def _cases() -> list[dict[str, object]]:
    decoded: object = json.loads(Path(__file__).with_name("fixtures.json").read_text(encoding="utf-8"))
    if not isinstance(decoded, list) or any(not isinstance(case, dict) for case in decoded):
        raise RuntimeError("jurisdiction fixtures must be a list of objects")
    return [cast(dict[str, object], case) for case in decoded]


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
    expected_kinds = case["expected_kinds"]
    assert isinstance(expected_kinds, list)
    assert all(isinstance(kind, str) for kind in expected_kinds)
    assert set(expected_kinds).issubset(kinds)
