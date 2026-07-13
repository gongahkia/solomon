# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator

from solomon.api.schemas import SolomonModel
from solomon.connectors import ConnectorConfiguration
from solomon.currency.models import _ensure_aware_utc, new_uuid7, now_utc


class DocumentSourceKind(str, Enum):
    FILESYSTEM = "filesystem"
    MICROSOFT_GRAPH = "microsoft-graph"
    API = "api"


class DocumentExtractionState(str, Enum):
    READY = "ready"
    REJECTED = "rejected"
    DELETED = "deleted"


class CandidateClaimStatus(str, Enum):
    PENDING = "pending"
    PROMOTED = "promoted"
    REJECTED = "rejected"


class DocumentSource(SolomonModel):
    id: str = Field(default_factory=new_uuid7)
    name: str = Field(min_length=1, max_length=120)
    kind: DocumentSourceKind
    root_ref: str = Field(min_length=1)
    enabled: bool = True
    config: ConnectorConfiguration = Field(default_factory=ConnectorConfiguration)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_datetimes(cls, value: datetime) -> datetime:
        return _ensure_aware_utc(value)

    @model_validator(mode="after")
    def validate_root_ref(self) -> DocumentSource:
        if self.kind is DocumentSourceKind.FILESYSTEM:
            if not Path(self.root_ref).is_absolute():
                raise ValueError("filesystem source root_ref must be an absolute path")
        elif self.kind is DocumentSourceKind.MICROSOFT_GRAPH:
            parsed = urlparse(self.root_ref)
            valid_graph_url = (
                parsed.scheme == "https"
                and parsed.netloc == "graph.microsoft.com"
                and parsed.path.startswith("/v1.0/")
            )
            if not valid_graph_url:
                raise ValueError("Microsoft Graph source root_ref must be an https://graph.microsoft.com/v1.0/ URL")
        return self


class SourceDocument(SolomonModel):
    id: str = Field(default_factory=new_uuid7)
    source_id: str
    external_id: str
    version: int = Field(ge=1, default=1)
    previous_version_id: str | None = None
    filename: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    content: str = Field(default="")
    content_sha256: str = ""
    extraction_state: DocumentExtractionState = DocumentExtractionState.READY
    extraction_reason: str | None = None
    ingested_at: datetime = Field(default_factory=now_utc)
    deleted_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ingested_at", "deleted_at")
    @classmethod
    def normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return _ensure_aware_utc(value) if value is not None else None

    def model_post_init(self, __context: Any) -> None:
        if not self.content_sha256:
            object.__setattr__(self, "content_sha256", hashlib.sha256(self.content.encode("utf-8")).hexdigest())


class CandidateClaim(SolomonModel):
    id: str = Field(default_factory=new_uuid7)
    document_id: str
    content: str = Field(min_length=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=1)
    status: CandidateClaimStatus = CandidateClaimStatus.PENDING
    promotion_item_id: str | None = None
    decision_by: str | None = None
    decision_reason: str | None = None
    created_at: datetime = Field(default_factory=now_utc)
    decided_at: datetime | None = None

    @field_validator("created_at", "decided_at")
    @classmethod
    def normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return _ensure_aware_utc(value) if value is not None else None
