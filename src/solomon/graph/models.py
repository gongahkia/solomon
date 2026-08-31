# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from solomon.api.schemas import SolomonModel
from solomon.currency.models import new_uuid7, now_utc


class EdgeType(str, Enum):
    INTERNAL_DEPENDS_ON_EXTERNAL = "internal_depends_on_external"
    INTERNAL_DEPENDS_ON_INTERNAL = "internal_depends_on_internal"
    SUPERSEDES = "supersedes"


class EdgeConfidence(str, Enum):
    HUMAN_ASSERTED = "human_asserted"
    HUMAN_CONFIRMED = "human_confirmed"
    LLM_SUGGESTED = "llm_suggested"


class DependencyEdge(SolomonModel):
    id: str = Field(default_factory=new_uuid7)
    source_id: str
    target_id: str
    edge_type: EdgeType
    target_kind: Literal["knowledge_item", "external_authority"]
    valid_from: datetime = Field(default_factory=now_utc)
    valid_to: datetime | None = None
    confidence: EdgeConfidence = EdgeConfidence.HUMAN_ASSERTED
    created_at: datetime = Field(default_factory=now_utc)
    created_by: str | None = None
    reason: str | None = None

    @field_validator("valid_from", "valid_to", "created_at")
    @classmethod
    def normalize_datetime(cls, value: datetime | None) -> datetime | None:
        from solomon.currency.models import _ensure_aware_utc

        if value is None:
            return None
        return _ensure_aware_utc(value)

    @model_validator(mode="after")
    def validate_edge_shape(self) -> DependencyEdge:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        if self.edge_type is EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL and self.target_kind != "external_authority":
            raise ValueError("external dependency edges must target an external authority")
        if self.edge_type in {EdgeType.INTERNAL_DEPENDS_ON_INTERNAL, EdgeType.SUPERSEDES}:
            if self.target_kind != "knowledge_item":
                raise ValueError("internal dependency and supersedes edges must target knowledge items")
        return self


class StalenessReason(SolomonModel):
    dependency_id: str
    changed_at: datetime
    reason: str
    edge_id: str | None = None
    change_id: str | None = None

    @field_validator("changed_at")
    @classmethod
    def normalize_changed_at(cls, value: datetime) -> datetime:
        from solomon.currency.models import _ensure_aware_utc

        return _ensure_aware_utc(value)


class ImpactResult(SolomonModel):
    changed_dependency_id: str
    stale_item_ids: list[str]
    reasons: dict[str, list[StalenessReason]]
    change_id: str | None = None
