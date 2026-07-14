from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from stonks_cli.vnext.custody_readiness import CustodyReadinessEvidence, CustodyReadinessOutcome
from stonks_cli.vnext.foundation import SecretReference

NOW = datetime(2026, 7, 14, 3, tzinfo=UTC)


def test_custody_readiness_evidence_is_secret_safe_serializable_and_time_bounded():
    evidence = _evidence()
    serialized = evidence.to_data()

    assert CustodyReadinessEvidence.from_data(serialized) == evidence
    assert serialized["key_reference"] == "env:STONKS_CLI_VENUE_KEY"
    assert evidence.is_current_at(NOW) is True
    assert evidence.is_current_at(NOW + timedelta(days=31)) is False


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"evidence_id": "00000000-0000-4000-8000-000000000001"},
        {
            "evidence_id": "00000000-0000-4000-8000-000000000001",
            "venue_id": "hyperliquid",
            "outcome": "ready",
            "key_reference": "key-value",
            "reviewer_id": "operator@example.test",
            "backup_verified_at": "2026-07-13T01:00:00Z",
            "recovery_tested_at": "2026-07-13T02:00:00Z",
            "reviewed_at": "2026-07-14T02:00:00Z",
            "valid_until": "2026-08-14T02:00:00Z",
            "source_url": "https://example.test/custody-review",
        },
    ],
)
def test_custody_readiness_evidence_fails_closed_for_missing_or_malformed_external_data(data):
    with pytest.raises(ValueError, match="custody-readiness evidence"):
        CustodyReadinessEvidence.from_data(data)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"venue_id": "Hyperliquid"},
        {"source_url": "http://example.test/custody-review"},
        {"recovery_tested_at": NOW - timedelta(days=3)},
        {"valid_until": NOW - timedelta(days=2)},
    ],
)
def test_custody_readiness_evidence_rejects_invalid_provenance(kwargs):
    values = _constructor_values()
    values.update(kwargs)

    with pytest.raises((TypeError, ValueError), match="custody-readiness"):
        CustodyReadinessEvidence(**values)


def _evidence() -> CustodyReadinessEvidence:
    return CustodyReadinessEvidence(**_constructor_values())


def _constructor_values() -> dict[str, object]:
    return {
        "evidence_id": UUID("00000000-0000-4000-8000-000000000001"),
        "venue_id": "hyperliquid",
        "outcome": CustodyReadinessOutcome.READY,
        "key_reference": SecretReference.parse("env:STONKS_CLI_VENUE_KEY"),
        "reviewer_id": "operator@example.test",
        "backup_verified_at": NOW - timedelta(days=2),
        "recovery_tested_at": NOW - timedelta(days=1),
        "reviewed_at": NOW,
        "valid_until": NOW + timedelta(days=30),
        "source_url": "https://www.example.test/custody-review",
    }
