# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from solomon.boundary.engine.client import BoundaryClient

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "boundary_accuracy_cases.json"


def test_vendored_boundary_accuracy_fixture_cases() -> None:
    client = BoundaryClient()
    cases: list[dict[str, Any]] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    for case in cases:
        response = client.review(
            request={
                "text": case["text"],
                "source_jurisdiction": case["source_jurisdiction"],
                "destination_jurisdiction": case["destination_jurisdiction"],
            }
        )
        kinds = {finding.kind for finding in response.findings}

        assert response.classification == case["expected_classification"], case["name"]
        assert set(case["expected_kinds"]).issubset(kinds), case["name"]


def test_vendored_boundary_rewrite_fixture_preserves_reidentification_and_opacity() -> None:
    client = BoundaryClient()
    text = "Send Jane Tan at jane@example.com the $2.5 billion draft."

    pseudonymized = client.pseudonymize(text)
    anonymized = client.anonymize(text)
    redacted = client.redact(text)
    reidentified = client.reidentify(pseudonymized.pseudonymized_text, mapping=pseudonymized.mapping)

    assert pseudonymized.mapping_persisted is False
    assert reidentified.reidentified_text == text
    for sensitive in ["Jane", "Tan", "jane@example.com"]:
        assert sensitive not in anonymized.anonymized_text
        assert sensitive not in redacted.redacted_text
    assert "[PERSON_1]" in anonymized.anonymized_text
    assert "[REDACTED_1]" in redacted.redacted_text
