# SPDX-License-Identifier: Apache-2.0
"""Kaypoh-derived local client facade vendored into Solomon."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from solomon.boundary.engine.mapping_store import VolatileMappingStore
from solomon.boundary.engine.review import (
    document_hash,
    pseudonymize_text,
    reidentify_text,
    review_text,
    scrub_document_base64,
)
from solomon.boundary.engine.schemas import (
    MappingEntry,
    PseudonymizeResponse,
    ReadyResponse,
    ReidentifyResponse,
    ReviewResponse,
)


class BoundaryClient:
    """In-process equivalent of the Kaypoh client surface Solomon needs."""

    def __init__(self, base_url: str | None = None, *, fail: bool = False, **_kwargs: Any) -> None:
        self.fail = fail
        self.base_url = base_url or "in-process://solomon-boundary-engine"
        self.mapping_store = VolatileMappingStore()

    def close(self) -> None:
        return None

    def __enter__(self) -> BoundaryClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def ready(self) -> ReadyResponse:
        self._raise_if_failed()
        return ReadyResponse()

    def review(
        self,
        text: str | None = None,
        *,
        request: Mapping[str, Any] | None = None,
        source_jurisdiction: str = "SG",
        destination_jurisdiction: str = "SG",
        **_kwargs: Any,
    ) -> ReviewResponse:
        self._raise_if_failed()
        payload = dict(request or {})
        resolved_text = str(payload.get("text", text or ""))
        source = str(payload.get("source_jurisdiction", source_jurisdiction))
        destination = str(payload.get("destination_jurisdiction", destination_jurisdiction))
        classification, findings = review_text(
            resolved_text,
            source_jurisdiction=source,
            destination_jurisdiction=destination,
        )
        return ReviewResponse(
            classification=classification,
            findings=findings,
            request_id=document_hash(f"review:{source}:{destination}:{resolved_text}")[:16],
        )

    def pseudonymize(
        self,
        text: str | None = None,
        *,
        request: Mapping[str, Any] | None = None,
        persist_mapping: bool = False,
        **_kwargs: Any,
    ) -> PseudonymizeResponse:
        self._raise_if_failed()
        payload = dict(request or {})
        resolved_text = str(payload.get("text", text or ""))
        sanitized, mapping = pseudonymize_text(resolved_text)
        doc_hash = document_hash(sanitized)
        if bool(payload.get("persist_mapping", persist_mapping)):
            self.mapping_store.put(doc_hash, mapping)
        return PseudonymizeResponse(pseudonymized_text=sanitized, mapping=mapping, document_hash=doc_hash)

    def anonymize(self, *args: Any, **kwargs: Any) -> PseudonymizeResponse:
        return self.pseudonymize(*args, **kwargs)

    def reidentify(
        self,
        anonymized_text: str | None = None,
        *,
        mapping: Sequence[MappingEntry | Mapping[str, Any]] | None = None,
        document_hash: str | None = None,
        request: Mapping[str, Any] | None = None,
    ) -> ReidentifyResponse:
        self._raise_if_failed()
        payload = dict(request or {})
        resolved_text = str(payload.get("anonymized_text", anonymized_text or ""))
        raw_mapping = mapping
        if raw_mapping is None and "mapping" in payload:
            raw_mapping = payload["mapping"]
        if raw_mapping is None and document_hash is not None:
            raw_mapping = self.mapping_store.pop(document_hash)
        entries = [
            entry if isinstance(entry, MappingEntry) else MappingEntry.model_validate(entry)
            for entry in list(raw_mapping or [])
        ]
        text, count = reidentify_text(resolved_text, entries)
        return ReidentifyResponse(reidentified_text=text, replacement_count=count)

    def scrub_document(
        self,
        document_base64: str | None = None,
        *,
        request: Mapping[str, Any] | None = None,
        **_kwargs: Any,
    ) -> dict[str, object]:
        self._raise_if_failed()
        payload = dict(request or {})
        resolved_document = str(payload.get("document_base64", document_base64 or ""))
        return scrub_document_base64(resolved_document)

    def _raise_if_failed(self) -> None:
        if self.fail:
            raise RuntimeError("vendored boundary engine unavailable")


KaypohClient = BoundaryClient
