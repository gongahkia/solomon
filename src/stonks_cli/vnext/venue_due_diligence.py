from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlparse
from uuid import UUID

from stonks_cli.vnext.foundation import as_utc

_JURISDICTION_PATTERN = re.compile(r"[A-Z]{2}\Z")
_REVIEWER_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]*\Z")
_VENUE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")


class VenueDueDiligenceOutcome(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class VenueDueDiligenceEvidence:
    evidence_id: UUID
    venue_id: str
    jurisdiction: str
    outcome: VenueDueDiligenceOutcome
    reviewer_id: str
    reviewed_at: datetime
    valid_until: datetime
    source_urls: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_id, UUID):
            raise TypeError("venue due-diligence evidence ID must be a UUID")
        if not isinstance(self.venue_id, str) or not _VENUE_ID_PATTERN.fullmatch(self.venue_id):
            raise ValueError("venue due-diligence venue ID is invalid")
        if not isinstance(self.jurisdiction, str) or not _JURISDICTION_PATTERN.fullmatch(self.jurisdiction):
            raise ValueError("venue due-diligence jurisdiction is invalid")
        if not isinstance(self.outcome, VenueDueDiligenceOutcome):
            raise TypeError("venue due-diligence outcome is invalid")
        if not isinstance(self.reviewer_id, str) or not _REVIEWER_ID_PATTERN.fullmatch(self.reviewer_id):
            raise ValueError("venue due-diligence reviewer ID is invalid")
        if not isinstance(self.source_urls, tuple) or not self.source_urls or len(set(self.source_urls)) != len(self.source_urls):
            raise ValueError("venue due-diligence source URLs are invalid")
        if not all(_is_https_url(source_url) for source_url in self.source_urls):
            raise ValueError("venue due-diligence source URLs are invalid")
        reviewed_at = as_utc(self.reviewed_at)
        valid_until = as_utc(self.valid_until)
        if valid_until <= reviewed_at:
            raise ValueError("venue due-diligence validity window is invalid")
        object.__setattr__(self, "reviewed_at", reviewed_at)
        object.__setattr__(self, "valid_until", valid_until)

    def is_current_at(self, timestamp: datetime) -> bool:
        current_at = as_utc(timestamp)
        return self.outcome is VenueDueDiligenceOutcome.ALLOWED and self.reviewed_at <= current_at < self.valid_until

    def to_data(self) -> dict[str, object]:
        return {
            "evidence_id": str(self.evidence_id),
            "venue_id": self.venue_id,
            "jurisdiction": self.jurisdiction,
            "outcome": self.outcome.value,
            "reviewer_id": self.reviewer_id,
            "reviewed_at": self.reviewed_at.isoformat().replace("+00:00", "Z"),
            "valid_until": self.valid_until.isoformat().replace("+00:00", "Z"),
            "source_urls": list(self.source_urls),
        }

    @classmethod
    def from_data(cls, data: object) -> VenueDueDiligenceEvidence:
        fields = {"evidence_id", "venue_id", "jurisdiction", "outcome", "reviewer_id", "reviewed_at", "valid_until", "source_urls"}
        if not isinstance(data, dict) or set(data) != fields:
            raise ValueError("venue due-diligence evidence fields are invalid")
        if not all(isinstance(data[field], str) for field in fields - {"source_urls"}) or not isinstance(data["source_urls"], list):
            raise ValueError("venue due-diligence evidence fields are invalid")
        try:
            return cls(
                UUID(data["evidence_id"]),
                data["venue_id"],
                data["jurisdiction"],
                VenueDueDiligenceOutcome(data["outcome"]),
                data["reviewer_id"],
                datetime.fromisoformat(data["reviewed_at"]),
                datetime.fromisoformat(data["valid_until"]),
                tuple(data["source_urls"]),
            )
        except (TypeError, ValueError) as error:
            raise ValueError("venue due-diligence evidence is malformed") from error


def _is_https_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)
