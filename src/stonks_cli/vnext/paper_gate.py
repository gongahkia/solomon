from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from stonks_cli.vnext.foundation import as_utc

_ACCOUNT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_REVIEWER_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]*\Z")


class PaperGateOutcome(StrEnum):
    PASSED = "passed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class PaperGateEvidence:
    evidence_id: UUID
    account_id: str
    outcome: PaperGateOutcome
    started_at: datetime
    completed_at: datetime
    minimum_days: int
    observed_days: int
    decision_count: int
    journal_sha256: str
    tearsheet_sha256: str
    reviewer_id: str
    reviewed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_id, UUID):
            raise TypeError("paper-gate evidence ID must be a UUID")
        if not isinstance(self.account_id, str) or not _ACCOUNT_ID_PATTERN.fullmatch(self.account_id):
            raise ValueError("paper-gate account ID is invalid")
        if not isinstance(self.outcome, PaperGateOutcome):
            raise TypeError("paper-gate outcome is invalid")
        if not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (self.minimum_days, self.observed_days, self.decision_count)):
            raise ValueError("paper-gate counters are invalid")
        if self.minimum_days < 1:
            raise ValueError("paper-gate minimum days is invalid")
        if not all(isinstance(value, str) and _DIGEST_PATTERN.fullmatch(value) for value in (self.journal_sha256, self.tearsheet_sha256)):
            raise ValueError("paper-gate artifact digests are invalid")
        if not isinstance(self.reviewer_id, str) or not _REVIEWER_ID_PATTERN.fullmatch(self.reviewer_id):
            raise ValueError("paper-gate reviewer ID is invalid")
        started_at = as_utc(self.started_at)
        completed_at = as_utc(self.completed_at)
        reviewed_at = as_utc(self.reviewed_at)
        if not started_at < completed_at <= reviewed_at:
            raise ValueError("paper-gate timestamps are invalid")
        if self.outcome is PaperGateOutcome.PASSED and (self.observed_days < self.minimum_days or self.decision_count < 1):
            raise ValueError("paper-gate pass evidence is insufficient")
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "completed_at", completed_at)
        object.__setattr__(self, "reviewed_at", reviewed_at)

    @property
    def passed(self) -> bool:
        return self.outcome is PaperGateOutcome.PASSED

    def to_data(self) -> dict[str, object]:
        return {
            "evidence_id": str(self.evidence_id),
            "account_id": self.account_id,
            "outcome": self.outcome.value,
            "started_at": _format_timestamp(self.started_at),
            "completed_at": _format_timestamp(self.completed_at),
            "minimum_days": self.minimum_days,
            "observed_days": self.observed_days,
            "decision_count": self.decision_count,
            "journal_sha256": self.journal_sha256,
            "tearsheet_sha256": self.tearsheet_sha256,
            "reviewer_id": self.reviewer_id,
            "reviewed_at": _format_timestamp(self.reviewed_at),
        }

    @classmethod
    def from_data(cls, data: object) -> PaperGateEvidence:
        string_fields = {"evidence_id", "account_id", "outcome", "started_at", "completed_at", "journal_sha256", "tearsheet_sha256", "reviewer_id", "reviewed_at"}
        integer_fields = {"minimum_days", "observed_days", "decision_count"}
        fields = string_fields | integer_fields
        if not isinstance(data, dict) or set(data) != fields:
            raise ValueError("paper-gate evidence fields are invalid")
        if not all(isinstance(data[field], str) for field in string_fields) or not all(type(data[field]) is int for field in integer_fields):
            raise ValueError("paper-gate evidence fields are invalid")
        try:
            return cls(
                UUID(data["evidence_id"]),
                data["account_id"],
                PaperGateOutcome(data["outcome"]),
                datetime.fromisoformat(data["started_at"]),
                datetime.fromisoformat(data["completed_at"]),
                data["minimum_days"],
                data["observed_days"],
                data["decision_count"],
                data["journal_sha256"],
                data["tearsheet_sha256"],
                data["reviewer_id"],
                datetime.fromisoformat(data["reviewed_at"]),
            )
        except (TypeError, ValueError) as error:
            raise ValueError("paper-gate evidence is malformed") from error


def _format_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
