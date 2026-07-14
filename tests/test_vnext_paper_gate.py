from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from stonks_cli.vnext.paper_gate import PaperGateEvidence, PaperGateOutcome

NOW = datetime(2026, 7, 14, 3, tzinfo=UTC)
DIGEST = "a" * 64


def test_paper_gate_evidence_binds_a_completed_paper_run_to_reviewed_artifacts():
    evidence = _evidence()

    assert PaperGateEvidence.from_data(evidence.to_data()) == evidence
    assert evidence.passed is True


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"evidence_id": "00000000-0000-4000-8000-000000000001"},
        {
            "evidence_id": "00000000-0000-4000-8000-000000000001",
            "account_id": "paper-account",
            "outcome": "passed",
            "started_at": "2026-06-14T03:00:00Z",
            "completed_at": "2026-07-14T03:00:00Z",
            "minimum_days": 30,
            "observed_days": 30,
            "decision_count": 4,
            "journal_sha256": "not-a-digest",
            "tearsheet_sha256": DIGEST,
            "reviewer_id": "operator@example.test",
            "reviewed_at": "2026-07-14T03:00:00Z",
        },
    ],
)
def test_paper_gate_evidence_fails_closed_for_missing_or_malformed_external_data(data):
    with pytest.raises(ValueError, match="paper-gate evidence"):
        PaperGateEvidence.from_data(data)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"minimum_days": 0},
        {"observed_days": 29},
        {"decision_count": 0},
        {"journal_sha256": "A" * 64},
        {"completed_at": NOW - timedelta(days=31)},
    ],
)
def test_paper_gate_pass_evidence_rejects_invalid_or_insufficient_provenance(kwargs):
    values = _constructor_values()
    values.update(kwargs)

    with pytest.raises((TypeError, ValueError), match="paper-gate"):
        PaperGateEvidence(**values)


def _evidence() -> PaperGateEvidence:
    return PaperGateEvidence(**_constructor_values())


def _constructor_values() -> dict[str, object]:
    return {
        "evidence_id": UUID("00000000-0000-4000-8000-000000000001"),
        "account_id": "paper-account",
        "outcome": PaperGateOutcome.PASSED,
        "started_at": NOW - timedelta(days=30),
        "completed_at": NOW - timedelta(minutes=1),
        "minimum_days": 30,
        "observed_days": 30,
        "decision_count": 4,
        "journal_sha256": DIGEST,
        "tearsheet_sha256": "b" * 64,
        "reviewer_id": "operator@example.test",
        "reviewed_at": NOW,
    }
