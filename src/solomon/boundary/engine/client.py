# SPDX-License-Identifier: Apache-2.0
"""Solomon local boundary client facade."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from solomon.boundary.engine.jurisdictions import supported_jurisdiction_codes
from solomon.boundary.engine.mapping_store import VolatileMappingStore
from solomon.boundary.engine.review import (
    DETECTOR_FAMILIES,
    anonymize_text,
    document_hash,
    pseudonymize_text,
    redact_text,
    reidentify_text,
    review_text,
    scrub_document_base64,
)
from solomon.boundary.engine.schemas import (
    AnonymizeResponse,
    BoundaryCapabilities,
    MappingEntry,
    PseudonymizeResponse,
    ReadyResponse,
    RedactResponse,
    ReidentifyResponse,
    ReviewResponse,
)


class BoundaryClient:
    """In-process Solomon boundary client surface."""

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

    def capabilities(self) -> BoundaryCapabilities:
        self._raise_if_failed()
        return BoundaryCapabilities(
            surfaces=["review", "pseudonymize", "anonymize", "redact", "reidentify", "documents/scrub"],
            privacy_operations=["pseudonymize", "anonymize", "redact", "reidentify"],
            jurisdiction_codes=supported_jurisdiction_codes(),
            detector_families=DETECTOR_FAMILIES,
        )

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
        resolved_text = _resolve_text(payload, text)
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
        resolved_text = _resolve_text(payload, text)
        sanitized, mapping = pseudonymize_text(resolved_text)
        doc_hash = document_hash(resolved_text)
        if bool(payload.get("persist_mapping", persist_mapping)):
            self.mapping_store.put(doc_hash, mapping)
        return PseudonymizeResponse(
            pseudonymized_text=sanitized,
            anonymized_text=sanitized,
            mapping=mapping,
            document_hash=doc_hash,
            mapping_persisted=bool(payload.get("persist_mapping", persist_mapping)),
        )

    def anonymize(self, *args: Any, **kwargs: Any) -> AnonymizeResponse:
        self._raise_if_failed()
        text = args[0] if args else None
        payload = dict(kwargs.get("request") or {})
        resolved_text = _resolve_text(payload, text if isinstance(text, str) else kwargs.get("text"))
        anonymized, replacements = anonymize_text(resolved_text)
        return AnonymizeResponse(
            anonymized_text=anonymized,
            replacements=replacements,
            document_hash=document_hash(resolved_text),
        )

    def redact(self, *args: Any, **kwargs: Any) -> RedactResponse:
        self._raise_if_failed()
        text = args[0] if args else None
        payload = dict(kwargs.get("request") or {})
        resolved_text = _resolve_text(payload, text if isinstance(text, str) else kwargs.get("text"))
        redacted, redactions = redact_text(resolved_text)
        return RedactResponse(
            redacted_text=redacted,
            redactions=redactions,
            document_hash=document_hash(resolved_text),
        )

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


def _resolve_text(payload: Mapping[str, Any], text: str | None) -> str:
    if payload.get("text") is not None:
        return str(payload["text"])
    if text is not None:
        return text
    if payload.get("document_base64") is not None:
        import base64

        decoded = base64.b64decode(str(payload["document_base64"]).encode("ascii"), validate=True)
        return decoded.decode("utf-8", errors="replace")
    return ""
