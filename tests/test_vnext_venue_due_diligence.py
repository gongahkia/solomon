from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from stonks_cli.vnext.venue_due_diligence import VenueDueDiligenceEvidence, VenueDueDiligenceOutcome

NOW = datetime(2026, 7, 14, 3, tzinfo=UTC)


def test_venue_due_diligence_evidence_is_serializable_and_current_only_when_allowed():
    evidence = _evidence()

    assert VenueDueDiligenceEvidence.from_data(evidence.to_data()) == evidence
    assert evidence.is_current_at(NOW) is True
    blocked = VenueDueDiligenceEvidence(
        evidence.evidence_id,
        evidence.venue_id,
        evidence.jurisdiction,
        VenueDueDiligenceOutcome.BLOCKED,
        evidence.reviewer_id,
        evidence.reviewed_at,
        evidence.valid_until,
        evidence.source_urls,
    )
    assert blocked.is_current_at(NOW) is False


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"evidence_id": "00000000-0000-4000-8000-000000000001"},
        {
            "evidence_id": "00000000-0000-4000-8000-000000000001",
            "venue_id": "hyperliquid",
            "jurisdiction": "SG",
            "outcome": "allowed",
            "reviewer_id": "operator@example.test",
            "reviewed_at": "2026-07-14T02:00:00Z",
            "valid_until": "2026-08-14T02:00:00Z",
            "source_urls": ["http://example.test/review"],
        },
    ],
)
def test_venue_due_diligence_evidence_fails_closed_for_missing_or_malformed_external_data(data):
    with pytest.raises(ValueError, match="venue due-diligence evidence"):
        VenueDueDiligenceEvidence.from_data(data)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"venue_id": "Hyperliquid"},
        {"jurisdiction": "Singapore"},
        {"reviewer_id": "operator id"},
        {"source_urls": ("https://example.test/review", "https://example.test/review")},
        {"valid_until": NOW - timedelta(seconds=1)},
    ],
)
def test_venue_due_diligence_evidence_rejects_invalid_provenance(kwargs):
    values = _evidence().to_data()
    values["evidence_id"] = UUID(values["evidence_id"])
    values["outcome"] = VenueDueDiligenceOutcome(values["outcome"])
    values["reviewed_at"] = NOW
    values["valid_until"] = NOW + timedelta(days=30)
    values["source_urls"] = tuple(values["source_urls"])
    values.update(kwargs)

    with pytest.raises((TypeError, ValueError), match="venue due-diligence"):
        VenueDueDiligenceEvidence(**values)


def _evidence() -> VenueDueDiligenceEvidence:
    return VenueDueDiligenceEvidence(
        UUID("00000000-0000-4000-8000-000000000001"),
        "hyperliquid",
        "SG",
        VenueDueDiligenceOutcome.ALLOWED,
        "operator@example.test",
        NOW - timedelta(days=1),
        NOW + timedelta(days=30),
        ("https://www.example.test/venue-review",),
    )
