# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from solomon.api.schemas import SolomonModel
from solomon.currency.models import _ensure_aware_utc, now_utc
from solomon.events import DomainEventEnvelope


class OutboxRecord(SolomonModel):
    event: DomainEventEnvelope
    available_at: datetime = Field(default_factory=now_utc)
    delivered_at: datetime | None = None
    delivery_attempts: int = Field(default=0, ge=0)
    last_error: str | None = None

    @field_validator("available_at", "delivered_at")
    @classmethod
    def normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return _ensure_aware_utc(value) if value is not None else None


__all__ = ["OutboxRecord"]
