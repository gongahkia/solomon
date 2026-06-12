# SPDX-License-Identifier: Apache-2.0
"""Kaypoh-derived boundary schemas vendored into Solomon."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ReadyResponse(BaseModel):
    ready: bool = True
    engine: str = "solomon.boundary.engine"
    source_commit: str = "7415069e57d69398e2c44ef6ababafb0c04a988b"


class ReviewFinding(BaseModel):
    kind: str
    text: str
    severity: str = "low"
    start: int | None = None
    end: int | None = None
    jurisdiction: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewResponse(BaseModel):
    classification: str
    findings: list[ReviewFinding] = Field(default_factory=list)
    request_id: str | None = None


class MappingEntry(BaseModel):
    placeholder: str
    original_text: str
    entity_type: str = "UNKNOWN"


class PlaceholderReplacement(BaseModel):
    placeholder: str
    entity_type: str
    start_char: int
    end_char: int


class OpaqueRedaction(BaseModel):
    marker: str
    start_char: int
    end_char: int


class PseudonymizeResponse(BaseModel):
    pseudonymized_text: str
    mapping: list[MappingEntry] = Field(default_factory=list)
    document_hash: str
    privacy_operation: str = "pseudonymize"
    anonymized_text: str | None = None
    mapping_persisted: bool = False


class AnonymizeResponse(BaseModel):
    anonymized_text: str
    document_hash: str
    replacements: list[PlaceholderReplacement] = Field(default_factory=list)
    privacy_operation: str = "anonymize"
    anonymization_mode: str = "placeholder_only"
    mapping_persisted: bool = False


class RedactResponse(BaseModel):
    redacted_text: str
    document_hash: str
    redactions: list[OpaqueRedaction] = Field(default_factory=list)
    privacy_operation: str = "redact"
    redaction_style: str = "opaque_text_marker"
    mapping_persisted: bool = False


class ReidentifyResponse(BaseModel):
    reidentified_text: str
    replacement_count: int


class BoundaryCapabilities(BaseModel):
    engine: str = "solomon.boundary.engine"
    source_commit: str = "7415069e57d69398e2c44ef6ababafb0c04a988b"
    surfaces: list[str]
    privacy_operations: list[str]
    jurisdiction_codes: list[str]
    detector_families: list[str]
    parity_reference: str = "../kaypoh/docs/schema.md"
