# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import secrets
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from solomon.api.schemas import SolomonModel

SCHEMA_VERSION = 1
_uuid7_lock = Lock()
_last_uuid7_ms = -1
_last_uuid7_counter = 0


class KnowledgeKind(str, Enum):
    POSITION = "position"
    CLAUSE = "clause"
    HOUSE_VIEW = "house-view"
    ADVICE = "advice"
    NOTE = "note"


class CurrencyState(str, Enum):
    LIVE = "Live"
    STALE_PENDING_REVERIFICATION = "StalePendingReverification"
    SUPERSEDED = "Superseded"
    RETIRED = "Retired"


class SourceKind(str, Enum):
    PARTNER = "partner"
    ASSOCIATE = "associate"
    MATTER_DOC = "matter-doc"
    EXTERNAL_FEED = "external-feed"
    MODEL = "model"


class CredenceTier(str, Enum):
    FIRM_AUTHORITATIVE = "FirmAuthoritative"
    VERIFIED = "Verified"
    MODEL_INFERRED = "ModelInferred"
    UNVERIFIED = "Unverified"


class VerifiedState(str, Enum):
    UNVERIFIED = "Unverified"
    VERIFIED = "Verified"
    NEEDS_REVIEW = "NeedsReview"
    REJECTED = "Rejected"


class KnowledgeContentRole(str, Enum):
    FACT = "fact"
    POSITION = "position"
    INSTRUCTION = "instruction"


class AuthorityKind(str, Enum):
    STATUTE = "statute"
    REGULATION = "regulation"
    CASE = "case"
    GUIDANCE = "guidance"


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def new_uuid7() -> str:
    """Return a UUIDv7 string on Python versions before uuid.uuid7 exists."""
    uuid7 = getattr(uuid, "uuid7", None)
    if uuid7 is not None:
        return str(uuid7())

    global _last_uuid7_counter, _last_uuid7_ms
    with _uuid7_lock:
        timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
        if timestamp_ms <= _last_uuid7_ms:
            timestamp_ms = _last_uuid7_ms
            _last_uuid7_counter = (_last_uuid7_counter + 1) & 0xFFF
            if _last_uuid7_counter == 0:
                timestamp_ms = (_last_uuid7_ms + 1) & ((1 << 48) - 1)
        else:
            _last_uuid7_counter = secrets.randbits(12)
        _last_uuid7_ms = timestamp_ms
        rand_a = _last_uuid7_counter
    rand_b = secrets.randbits(62)
    value = (timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))


class Client(SolomonModel):
    id: str = Field(default_factory=new_uuid7)
    name: str
    external_ref: str | None = None


class Matter(SolomonModel):
    id: str = Field(default_factory=new_uuid7)
    client_id: str
    name: str
    external_ref: str | None = None
    sensitivity: Literal["standard", "confidential", "strict"] = "standard"


class AuthorityVersion(SolomonModel):
    version: str
    effective_from: datetime
    source_ref: str | None = None
    note: str | None = None

    @field_validator("effective_from")
    @classmethod
    def normalize_effective_from(cls, value: datetime) -> datetime:
        return _ensure_aware_utc(value)


class ExternalAuthority(SolomonModel):
    id: str = Field(default_factory=new_uuid7)
    kind: AuthorityKind
    reference: str
    jurisdiction: str
    current_version: str
    version_history: list[AuthorityVersion] = Field(default_factory=list)


class Provenance(SolomonModel):
    source_kind: SourceKind
    source_ref: str
    author: str | None = None
    matter_id: str | None = None
    boundary_review_classification: str | None = None
    boundary_findings: list[dict[str, Any]] = Field(default_factory=list)


class KnowledgeItem(SolomonModel):
    id: str = Field(default_factory=new_uuid7)
    schema_version: int = SCHEMA_VERSION
    kind: KnowledgeKind
    content_role: KnowledgeContentRole = KnowledgeContentRole.POSITION
    content: str
    embedding_ref: str | None = None
    provenance: Provenance
    valid_from: datetime = Field(default_factory=now_utc)
    valid_to: datetime | None = None
    ingested_at: datetime = Field(default_factory=now_utc)
    credence_tier: CredenceTier = CredenceTier.UNVERIFIED
    currency_state: CurrencyState = CurrencyState.LIVE
    verified_state: VerifiedState = VerifiedState.UNVERIFIED
    last_verified_at: datetime | None = None
    verified_by: str | None = None
    matter_id: str | None = None
    client_id: str | None = None
    successor_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("valid_from", "valid_to", "ingested_at", "last_verified_at")
    @classmethod
    def normalize_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _ensure_aware_utc(value)

    @model_validator(mode="after")
    def validate_temporal_order(self) -> KnowledgeItem:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {self.schema_version}")
        return self

    def superseded_copy(self, *, successor_id: str, valid_to: datetime) -> KnowledgeItem:
        return self.model_copy(
            update={
                "valid_to": _ensure_aware_utc(valid_to),
                "currency_state": CurrencyState.SUPERSEDED,
                "successor_id": successor_id,
            }
        )
