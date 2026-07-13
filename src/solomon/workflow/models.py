# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from solomon.api.schemas import SolomonModel
from solomon.currency.models import _ensure_aware_utc, new_uuid7, now_utc


class ReviewTaskState(str, Enum):
    OPEN = "open"
    ASSIGNED = "assigned"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"


class ReviewTaskPriority(str, Enum):
    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"


class AuthorityChangeEvent(SolomonModel):
    id: str = Field(default_factory=new_uuid7)
    source_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    authority_id: str = Field(min_length=1)
    previous_version: str | None = None
    new_version: str = Field(min_length=1)
    changed_at: datetime
    evidence_url: str | None = None
    evidence_sha256: str | None = None
    diff: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime = Field(default_factory=now_utc)

    @field_validator("changed_at", "received_at")
    @classmethod
    def normalize_datetimes(cls, value: datetime) -> datetime:
        return _ensure_aware_utc(value)

    def model_post_init(self, __context: object) -> None:
        if self.evidence_url and not self.evidence_sha256:
            object.__setattr__(self, "evidence_sha256", hashlib.sha256(self.evidence_url.encode("utf-8")).hexdigest())


class ReviewTask(SolomonModel):
    id: str = Field(default_factory=new_uuid7)
    event_id: str
    item_id: str
    priority: ReviewTaskPriority
    reason: str = Field(min_length=1)
    state: ReviewTaskState = ReviewTaskState.OPEN
    reviewer_id: str | None = None
    assigned_by: str | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    resolved_at: datetime | None = None

    @field_validator("created_at", "updated_at", "resolved_at")
    @classmethod
    def normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return _ensure_aware_utc(value) if value is not None else None
