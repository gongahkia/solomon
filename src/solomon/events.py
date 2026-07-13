# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from solomon.api.schemas import SolomonModel
from solomon.currency.models import _ensure_aware_utc, new_uuid7, now_utc

DOMAIN_EVENT_SCHEMA_VERSION = "solomon.domain_event.v1"


class DomainEventEnvelope(SolomonModel):
    event_id: str = Field(default_factory=new_uuid7)
    schema_version: str = DOMAIN_EVENT_SCHEMA_VERSION
    event_version: int = Field(default=1, ge=1)
    event_type: str = Field(min_length=1)
    aggregate_type: str = Field(min_length=1)
    aggregate_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    occurred_at: datetime = Field(default_factory=now_utc)
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_sha256: str = ""

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        return _ensure_aware_utc(value)

    @model_validator(mode="after")
    def validate_payload_sha256(self) -> DomainEventEnvelope:
        payload_sha256 = self.payload_digest(self.payload)
        if self.payload_sha256 and self.payload_sha256 != payload_sha256:
            raise ValueError("payload_sha256 does not match payload")
        if not self.payload_sha256:
            object.__setattr__(self, "payload_sha256", payload_sha256)
        return self

    @staticmethod
    def payload_digest(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


__all__ = ["DOMAIN_EVENT_SCHEMA_VERSION", "DomainEventEnvelope"]
