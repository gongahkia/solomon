# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any, Literal, Protocol, cast

from pydantic import BaseModel, Field

from solomon.boundary.engine.client import BoundaryClient
from solomon.currency.models import KnowledgeItem


class BoundaryImportStatus(BaseModel):
    importable: bool
    engine_path: str
    client_path: str
    detail: str


class BoundaryUnavailableError(RuntimeError):
    """Raised when the Solomon boundary is unavailable and Solomon must fail closed."""


class BoundaryRefusedError(RuntimeError):
    """Raised when Solomon boundary policy refuses an unsafe item or egress."""


class BoundaryClientProtocol(Protocol):
    def review(self, *args: Any, **kwargs: Any) -> Any: ...

    def pseudonymize(self, *args: Any, **kwargs: Any) -> Any: ...

    def reidentify(self, *args: Any, **kwargs: Any) -> Any: ...

    def scrub_document(self, *args: Any, **kwargs: Any) -> Any: ...


class BoundaryPolicy(BaseModel):
    unsafe_classifications: set[str] = Field(default_factory=lambda: {"HIGH_RISK"})
    unsafe_action: Literal["refuse", "quarantine"] = "quarantine"
    default_source_jurisdiction: str = "SG"
    default_destination_jurisdiction: str = "SG"
    review_profile: Literal["strict", "audit_grade"] = "strict"
    llm_input_mode: Literal["structured_tokens", "raw_text"] = "structured_tokens"
    raw_text_matter_opt_ins: set[str] = Field(default_factory=set)


class BoundaryReview(BaseModel):
    classification: str
    action: Literal["allow", "quarantine", "refuse"]
    findings: list[dict[str, Any]] = Field(default_factory=list)
    request_id: str | None = None


class SanitizedContext(BaseModel):
    context_id: str
    sanitized_text: str
    mapping_count: int
    document_hash: str | None = None
    source_jurisdiction: str
    destination_jurisdiction: str
    input_mode: Literal["structured_tokens", "raw_text"]


class DemaskingResult(BaseModel):
    text: str
    replacements: int
    mapping_flushed: bool


class PlaceholderSurvivalResult(BaseModel):
    ok: bool
    missing_placeholders: list[str] = Field(default_factory=list)
    present_placeholders: list[str] = Field(default_factory=list)


def _model_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return cast(dict[str, Any], value.model_dump(mode="json"))
    if isinstance(value, dict):
        return value
    return dict(vars(value))


def _response_field(value: Any, field: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(field, default)
    return getattr(value, field, default)


def _classification_text(value: Any) -> str:
    classification = _response_field(value, "classification", "SAFE")
    return str(getattr(classification, "value", classification))


def _mapping_for_reidentify(mapping: list[Any]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for entry in mapping:
        data = _model_dump(entry)
        placeholder = str(data.get("placeholder", ""))
        original_text = str(data.get("original_text", ""))
        if placeholder and original_text:
            entries.append({"placeholder": placeholder, "original_text": original_text})
    return entries


def load_boundary_client_class(_boundary_engine_path: object | None = None) -> type[Any]:
    """Return Solomon's in-process boundary client class."""
    return BoundaryClient


def probe_boundary_client(_boundary_engine_path: object | None = None) -> BoundaryImportStatus:
    client_path = "src/solomon/boundary/engine/client.py"
    try:
        load_boundary_client_class()
    except Exception as exc:  # pragma: no cover - detail is environment-dependent
        return BoundaryImportStatus(
            importable=False,
            engine_path="src/solomon/boundary/engine",
            client_path=client_path,
            detail=str(exc),
        )
    return BoundaryImportStatus(
        importable=True,
        engine_path="src/solomon/boundary/engine",
        client_path=client_path,
        detail="Solomon boundary client import succeeded",
    )


class SolomonBoundary:
    def __init__(
        self,
        client: BoundaryClientProtocol | None = None,
        *,
        policy: BoundaryPolicy | None = None,
    ) -> None:
        self.client = client or BoundaryClient()
        self.policy = policy or BoundaryPolicy()
        self._volatile_mappings: dict[str, list[dict[str, str]]] = {}

    def review_for_ingest(
        self,
        item: KnowledgeItem,
        *,
        source_jurisdiction: str | None = None,
        destination_jurisdiction: str | None = None,
    ) -> tuple[KnowledgeItem, BoundaryReview]:
        resolved_source = source_jurisdiction or self.policy.default_source_jurisdiction
        resolved_destination = destination_jurisdiction or self.policy.default_destination_jurisdiction
        try:
            response = self.client.review(
                request={
                    "text": item.content,
                    "source_jurisdiction": resolved_source,
                    "destination_jurisdiction": resolved_destination,
                    "document_type": item.kind.value,
                    "review_profile": self.policy.review_profile,
                    "matter_id": item.matter_id,
                    "include_suggestions": True,
                }
            )
        except Exception as exc:  # pragma: no cover - exact client failures depend on transport
            raise BoundaryUnavailableError("boundary review failed; refusing ingestion") from exc

        classification = _classification_text(response)
        findings = [_model_dump(finding) for finding in _response_field(response, "findings", [])]
        action: Literal["allow", "quarantine", "refuse"] = "allow"
        if classification in self.policy.unsafe_classifications:
            action = self.policy.unsafe_action

        review = BoundaryReview(
            classification=classification,
            action=action,
            findings=findings,
            request_id=cast(str | None, _response_field(response, "request_id")),
        )
        if action == "refuse":
            raise BoundaryRefusedError(f"boundary classified item {item.id} as {classification}")

        provenance = item.provenance.model_copy(
            update={
                "boundary_review_classification": classification,
                "boundary_findings": findings,
            }
        )
        metadata = dict(item.metadata)
        if action == "quarantine":
            metadata["boundary_quarantine"] = {"classification": classification, "request_id": review.request_id}
        return item.model_copy(update={"provenance": provenance, "metadata": metadata}), review

    def sanitize_context(
        self,
        text: str,
        *,
        matter_id: str | None = None,
        source_jurisdiction: str | None = None,
        destination_jurisdiction: str | None = None,
        input_mode: Literal["structured_tokens", "raw_text"] | None = None,
    ) -> SanitizedContext:
        resolved_mode = input_mode or self.policy.llm_input_mode
        resolved_source = source_jurisdiction or self.policy.default_source_jurisdiction
        resolved_destination = destination_jurisdiction or self.policy.default_destination_jurisdiction
        if resolved_mode == "raw_text" and (matter_id is None or matter_id not in self.policy.raw_text_matter_opt_ins):
            raise BoundaryRefusedError("raw_text egress requires explicit per-matter opt-in")
        try:
            response = self.client.pseudonymize(
                request={
                    "text": text,
                    "source_jurisdiction": resolved_source,
                    "destination_jurisdiction": resolved_destination,
                    "document_type": "model_context",
                    "review_profile": self.policy.review_profile,
                    "matter_id": matter_id,
                    "include_suggestions": True,
                    "include_mnpi_scalars": True,
                    "persist_mapping": False,
                    "llm_input_mode": resolved_mode,
                }
            )
        except Exception as exc:  # pragma: no cover - exact client failures depend on transport
            raise BoundaryUnavailableError("boundary pseudonymize failed; refusing model egress") from exc

        mapping = _mapping_for_reidentify(list(_response_field(response, "mapping", [])))
        context_id = str(_response_field(response, "document_hash", "")) or (
            f"volatile:{len(self._volatile_mappings) + 1}"
        )
        self._volatile_mappings[context_id] = mapping
        sanitized_text = str(
            _response_field(response, "pseudonymized_text", _response_field(response, "anonymized_text", text))
        )
        return SanitizedContext(
            context_id=context_id,
            sanitized_text=sanitized_text,
            mapping_count=len(mapping),
            document_hash=cast(str | None, _response_field(response, "document_hash")),
            source_jurisdiction=resolved_source,
            destination_jurisdiction=resolved_destination,
            input_mode=resolved_mode,
        )

    def reidentify_response(self, context_id: str, model_text: str) -> DemaskingResult:
        mapping = self._volatile_mappings.get(context_id)
        if mapping is None:
            raise BoundaryRefusedError("no volatile mapping for context; refusing demasking")
        try:
            response = self.client.reidentify(anonymized_text=model_text, mapping=mapping)
        except Exception as exc:  # pragma: no cover - exact client failures depend on transport
            raise BoundaryUnavailableError("boundary reidentify failed") from exc
        finally:
            self._volatile_mappings.pop(context_id, None)

        return DemaskingResult(
            text=str(_response_field(response, "reidentified_text", _response_field(response, "text", model_text))),
            replacements=int(
                _response_field(response, "replacement_count", _response_field(response, "replacements", 0))
            ),
            mapping_flushed=context_id not in self._volatile_mappings,
        )

    def scrub_document(
        self,
        *,
        document_base64: str,
        document_filename: str | None = None,
        document_mime_type: str | None = None,
    ) -> Any:
        try:
            return self.client.scrub_document(
                document_base64=document_base64,
                document_filename=document_filename,
                document_mime_type=document_mime_type,
            )
        except Exception as exc:  # pragma: no cover - exact client failures depend on transport
            raise BoundaryUnavailableError("boundary document scrub failed; refusing ingestion") from exc

    def volatile_mapping_count(self) -> int:
        return len(self._volatile_mappings)


def check_placeholder_survival(response_text: str, mapping: list[dict[str, str]]) -> PlaceholderSurvivalResult:
    present: list[str] = []
    missing: list[str] = []
    for entry in mapping:
        placeholder = entry["placeholder"]
        if placeholder in response_text:
            present.append(placeholder)
        else:
            missing.append(placeholder)
    return PlaceholderSurvivalResult(ok=not missing, missing_placeholders=missing, present_placeholders=present)
