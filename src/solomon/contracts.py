# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import Field, field_validator

from solomon.api.schemas import SolomonModel
from solomon.connectors import ConnectorConfiguration
from solomon.currency.models import _ensure_aware_utc, now_utc
from solomon.sources.models import DocumentSource, DocumentSourceKind
from solomon.workflow.models import AuthorityChangeEvent, ReviewTask

DOMAIN_CONTRACT_VERSION = "solomon.domain.v1"


class ContractModel(SolomonModel):
    schema_version: str = DOMAIN_CONTRACT_VERSION


class AdapterHealth(ContractModel):
    healthy: bool
    checked_at: datetime = Field(default_factory=now_utc)
    detail: str | None = None

    @field_validator("checked_at")
    @classmethod
    def normalize_checked_at(cls, value: datetime) -> datetime:
        return _ensure_aware_utc(value)


class SyncCheckpoint(ContractModel):
    source_id: str = Field(min_length=1)
    cursor: str = Field(min_length=1)
    observed_at: datetime = Field(default_factory=now_utc)

    @field_validator("observed_at")
    @classmethod
    def normalize_observed_at(cls, value: datetime) -> datetime:
        return _ensure_aware_utc(value)


class DiscoveredDocument(ContractModel):
    external_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    content_ref: str = Field(min_length=1)
    modified_at: datetime | None = None
    mime_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("modified_at")
    @classmethod
    def normalize_modified_at(cls, value: datetime | None) -> datetime | None:
        return _ensure_aware_utc(value) if value is not None else None


class AuthoritySourceKind(str, Enum):
    API = "api"
    FEED = "feed"
    WEBHOOK = "webhook"


class AuthorityPollSchedule(SolomonModel):
    interval_seconds: int = Field(default=3600, ge=60)
    jitter_seconds: int = Field(default=0, ge=0)

    @field_validator("jitter_seconds")
    @classmethod
    def validate_jitter(cls, value: int, info: Any) -> int:
        interval = info.data.get("interval_seconds", 3600)
        if value >= interval:
            raise ValueError("jitter_seconds must be less than interval_seconds")
        return value


class AuthoritySource(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=120)
    kind: AuthoritySourceKind
    root_ref: str = Field(min_length=1)
    canonical_namespace: str = Field(default="default", pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    enabled: bool = True
    config: ConnectorConfiguration = Field(default_factory=ConnectorConfiguration)
    poll_schedule: AuthorityPollSchedule = Field(default_factory=AuthorityPollSchedule)


class AuthorityObservation(ContractModel):
    authority_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    effective_at: datetime
    evidence_url: str | None = None
    evidence_sha256: str | None = None
    diff: dict[str, Any] = Field(default_factory=dict)

    @field_validator("effective_at")
    @classmethod
    def normalize_effective_at(cls, value: datetime) -> datetime:
        return _ensure_aware_utc(value)


class EmbeddingRequest(ContractModel):
    model: str = Field(min_length=1)
    texts: list[str] = Field(min_length=1)


class EmbeddingResponse(ContractModel):
    model: str = Field(min_length=1)
    vectors: list[list[float]] = Field(min_length=1)


class ReviewDispatch(ContractModel):
    task: ReviewTask
    destination: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


class ReviewDispatchResult(ContractModel):
    delivery_id: str = Field(min_length=1)
    accepted_at: datetime = Field(default_factory=now_utc)

    @field_validator("accepted_at")
    @classmethod
    def normalize_accepted_at(cls, value: datetime) -> datetime:
        return _ensure_aware_utc(value)


class WebhookEvent(ContractModel):
    event_type: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    occurred_at: datetime = Field(default_factory=now_utc)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        return _ensure_aware_utc(value)


class WebhookDelivery(ContractModel):
    event: WebhookEvent
    target_url: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


class WebhookDeliveryResult(ContractModel):
    delivery_id: str = Field(min_length=1)
    status_code: int = Field(ge=100, le=599)
    delivered_at: datetime = Field(default_factory=now_utc)

    @field_validator("delivered_at")
    @classmethod
    def normalize_delivered_at(cls, value: datetime) -> datetime:
        return _ensure_aware_utc(value)


@runtime_checkable
class DocumentSourceAdapter(Protocol):
    kind: DocumentSourceKind

    def health(self, source: DocumentSource) -> AdapterHealth: ...

    def discover(
        self,
        source: DocumentSource,
        checkpoint: SyncCheckpoint | None,
    ) -> tuple[list[DiscoveredDocument], SyncCheckpoint | None]: ...


@runtime_checkable
class AuthoritySourceAdapter(Protocol):
    kind: AuthoritySourceKind

    def health(self, source: AuthoritySource) -> AdapterHealth: ...

    def poll(
        self,
        source: AuthoritySource,
        checkpoint: SyncCheckpoint | None,
    ) -> tuple[list[AuthorityChangeEvent], SyncCheckpoint | None]: ...

    def checkpoint(self, source: AuthoritySource) -> SyncCheckpoint | None: ...

    def replay(self, source: AuthoritySource, checkpoint: SyncCheckpoint) -> list[AuthorityChangeEvent]: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse: ...


@runtime_checkable
class ReviewDispatcher(Protocol):
    def dispatch(self, dispatch: ReviewDispatch) -> ReviewDispatchResult: ...


@runtime_checkable
class WebhookDispatcher(Protocol):
    def deliver(self, delivery: WebhookDelivery) -> WebhookDeliveryResult: ...


__all__ = [
    "DOMAIN_CONTRACT_VERSION",
    "AdapterHealth",
    "AuthorityObservation",
    "AuthoritySource",
    "AuthoritySourceAdapter",
    "AuthoritySourceKind",
    "AuthorityPollSchedule",
    "ContractModel",
    "DiscoveredDocument",
    "DocumentSourceAdapter",
    "EmbeddingProvider",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "ReviewDispatch",
    "ReviewDispatcher",
    "ReviewDispatchResult",
    "SyncCheckpoint",
    "WebhookDelivery",
    "WebhookDeliveryResult",
    "WebhookDispatcher",
    "WebhookEvent",
]
