# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from pydantic import Field, field_validator

from solomon.api.schemas import SolomonModel
from solomon.contracts import SyncCheckpoint
from solomon.currency.models import _ensure_aware_utc
from solomon.sources.models import DocumentSource, DocumentSourceKind
from solomon.sources.store import SQLiteDocumentStore


class GraphResponse(Protocol):
    status_code: int

    def json(self) -> Mapping[str, Any]: ...


class GraphTransport(Protocol):
    def get(self, url: str) -> GraphResponse: ...


class MicrosoftGraphDeltaChange(SolomonModel):
    source_id: str
    external_id: str
    kind: str
    filename: str | None = None
    content_ref: str | None = None
    modified_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("modified_at")
    @classmethod
    def normalize_modified_at(cls, value: datetime | None) -> datetime | None:
        return _ensure_aware_utc(value) if value is not None else None


class MicrosoftGraphDeltaResult(SolomonModel):
    source_id: str
    changes: list[MicrosoftGraphDeltaChange]
    checkpoint: SyncCheckpoint
    resynchronized: bool = False


class MicrosoftGraphDeltaError(ValueError):
    pass


class MicrosoftGraphDeltaSynchronizer:
    def __init__(self, store: SQLiteDocumentStore, transport: GraphTransport, *, max_retries: int = 2) -> None:
        self.store = store
        self.transport = transport
        self.max_retries = max_retries

    def sync(self, source_id: str) -> MicrosoftGraphDeltaResult:
        source = self.store.get_source(source_id)
        if source.kind is not DocumentSourceKind.MICROSOFT_GRAPH:
            raise MicrosoftGraphDeltaError("Microsoft Graph synchronizer requires a Microsoft Graph source")
        checkpoint = self.store.get_sync_checkpoint(source_id)
        url = checkpoint.cursor if checkpoint is not None else source.root_ref
        resynchronized = False
        while True:
            response = self._get_with_retry(url)
            if response.status_code == 410 and not resynchronized:
                url = source.root_ref
                resynchronized = True
                continue
            if response.status_code == 410:
                raise MicrosoftGraphDeltaError("Microsoft Graph delta cursor expired during resynchronization")
            if response.status_code < 200 or response.status_code >= 300:
                raise MicrosoftGraphDeltaError(f"Microsoft Graph request failed with status {response.status_code}")
            changes, next_url, delta_url = _parse_page(source, response.json())
            all_changes = list(changes)
            while next_url is not None:
                page = self._get_with_retry(next_url)
                if page.status_code < 200 or page.status_code >= 300:
                    raise MicrosoftGraphDeltaError(f"Microsoft Graph request failed with status {page.status_code}")
                changes, next_url, page_delta_url = _parse_page(source, page.json())
                all_changes.extend(changes)
                delta_url = page_delta_url or delta_url
            if delta_url is None:
                raise MicrosoftGraphDeltaError("Microsoft Graph delta response omitted @odata.deltaLink")
            next_checkpoint = SyncCheckpoint(source_id=source.id, cursor=delta_url)
            self.store.set_sync_checkpoint(next_checkpoint)
            return MicrosoftGraphDeltaResult(
                source_id=source.id,
                changes=all_changes,
                checkpoint=next_checkpoint,
                resynchronized=resynchronized,
            )

    def _get_with_retry(self, url: str) -> GraphResponse:
        for attempt in range(self.max_retries + 1):
            response = self.transport.get(url)
            if response.status_code not in {429, 500, 502, 503, 504} or attempt == self.max_retries:
                return response
        raise MicrosoftGraphDeltaError("unreachable Microsoft Graph retry state")


def _parse_page(
    source: DocumentSource,
    payload: Mapping[str, Any],
) -> tuple[list[MicrosoftGraphDeltaChange], str | None, str | None]:
    entries = payload.get("value")
    if not isinstance(entries, list):
        raise MicrosoftGraphDeltaError("Microsoft Graph delta response requires a value list")
    changes = [_change_from_entry(source, entry) for entry in entries]
    next_url = payload.get("@odata.nextLink")
    delta_url = payload.get("@odata.deltaLink")
    if next_url is not None and not isinstance(next_url, str):
        raise MicrosoftGraphDeltaError("Microsoft Graph @odata.nextLink must be a string")
    if delta_url is not None and not isinstance(delta_url, str):
        raise MicrosoftGraphDeltaError("Microsoft Graph @odata.deltaLink must be a string")
    return changes, next_url, delta_url


def _change_from_entry(source: DocumentSource, entry: object) -> MicrosoftGraphDeltaChange:
    if not isinstance(entry, Mapping):
        raise MicrosoftGraphDeltaError("Microsoft Graph delta entry must be an object")
    external_id = entry.get("id")
    if not isinstance(external_id, str) or not external_id:
        raise MicrosoftGraphDeltaError("Microsoft Graph delta entry requires id")
    deleted = "deleted" in entry
    name = entry.get("name")
    web_url = entry.get("webUrl")
    modified = entry.get("lastModifiedDateTime")
    if not deleted and (not isinstance(name, str) or not isinstance(web_url, str)):
        raise MicrosoftGraphDeltaError("Microsoft Graph live entry requires name and webUrl")
    return MicrosoftGraphDeltaChange(
        source_id=source.id,
        external_id=external_id,
        kind="deleted" if deleted else "upsert",
        filename=name if isinstance(name, str) else None,
        content_ref=web_url if isinstance(web_url, str) else None,
        modified_at=_parse_datetime(modified) if isinstance(modified, str) else None,
        metadata={"etag": entry.get("eTag"), "parent_reference": entry.get("parentReference")},
    )


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


__all__ = [
    "GraphResponse",
    "GraphTransport",
    "MicrosoftGraphDeltaChange",
    "MicrosoftGraphDeltaError",
    "MicrosoftGraphDeltaResult",
    "MicrosoftGraphDeltaSynchronizer",
]
