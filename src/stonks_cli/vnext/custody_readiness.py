from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlparse
from uuid import UUID

from stonks_cli.vnext.foundation import SecretReference, as_utc

_REVIEWER_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]*\Z")
_VENUE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")


class CustodyReadinessOutcome(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class CustodyReadinessEvidence:
    evidence_id: UUID
    venue_id: str
    outcome: CustodyReadinessOutcome
    key_reference: SecretReference
    reviewer_id: str
    backup_verified_at: datetime
    recovery_tested_at: datetime
    reviewed_at: datetime
    valid_until: datetime
    source_url: str

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_id, UUID):
            raise TypeError("custody-readiness evidence ID must be a UUID")
        if not isinstance(self.venue_id, str) or not _VENUE_ID_PATTERN.fullmatch(self.venue_id):
            raise ValueError("custody-readiness venue ID is invalid")
        if not isinstance(self.outcome, CustodyReadinessOutcome):
            raise TypeError("custody-readiness outcome is invalid")
        if not isinstance(self.key_reference, SecretReference):
            raise TypeError("custody-readiness key reference is invalid")
        if not isinstance(self.reviewer_id, str) or not _REVIEWER_ID_PATTERN.fullmatch(self.reviewer_id):
            raise ValueError("custody-readiness reviewer ID is invalid")
        if not _is_https_url(self.source_url):
            raise ValueError("custody-readiness source URL is invalid")
        backup_verified_at = as_utc(self.backup_verified_at)
        recovery_tested_at = as_utc(self.recovery_tested_at)
        reviewed_at = as_utc(self.reviewed_at)
        valid_until = as_utc(self.valid_until)
        if not backup_verified_at <= recovery_tested_at <= reviewed_at < valid_until:
            raise ValueError("custody-readiness timestamps are invalid")
        object.__setattr__(self, "backup_verified_at", backup_verified_at)
        object.__setattr__(self, "recovery_tested_at", recovery_tested_at)
        object.__setattr__(self, "reviewed_at", reviewed_at)
        object.__setattr__(self, "valid_until", valid_until)

    def is_current_at(self, timestamp: datetime) -> bool:
        current_at = as_utc(timestamp)
        return self.outcome is CustodyReadinessOutcome.READY and self.reviewed_at <= current_at < self.valid_until

    def to_data(self) -> dict[str, object]:
        return {
            "evidence_id": str(self.evidence_id),
            "venue_id": self.venue_id,
            "outcome": self.outcome.value,
            "key_reference": str(self.key_reference),
            "reviewer_id": self.reviewer_id,
            "backup_verified_at": _format_timestamp(self.backup_verified_at),
            "recovery_tested_at": _format_timestamp(self.recovery_tested_at),
            "reviewed_at": _format_timestamp(self.reviewed_at),
            "valid_until": _format_timestamp(self.valid_until),
            "source_url": self.source_url,
        }

    @classmethod
    def from_data(cls, data: object) -> CustodyReadinessEvidence:
        fields = {
            "evidence_id",
            "venue_id",
            "outcome",
            "key_reference",
            "reviewer_id",
            "backup_verified_at",
            "recovery_tested_at",
            "reviewed_at",
            "valid_until",
            "source_url",
        }
        if not isinstance(data, dict) or set(data) != fields or not all(isinstance(data[field], str) for field in fields):
            raise ValueError("custody-readiness evidence fields are invalid")
        try:
            return cls(
                UUID(data["evidence_id"]),
                data["venue_id"],
                CustodyReadinessOutcome(data["outcome"]),
                SecretReference.parse(data["key_reference"]),
                data["reviewer_id"],
                datetime.fromisoformat(data["backup_verified_at"]),
                datetime.fromisoformat(data["recovery_tested_at"]),
                datetime.fromisoformat(data["reviewed_at"]),
                datetime.fromisoformat(data["valid_until"]),
                data["source_url"],
            )
        except (TypeError, ValueError) as error:
            raise ValueError("custody-readiness evidence is malformed") from error


def _format_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _is_https_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)
