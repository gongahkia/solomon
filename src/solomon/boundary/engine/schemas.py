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


class PseudonymizeResponse(BaseModel):
    pseudonymized_text: str
    mapping: list[MappingEntry] = Field(default_factory=list)
    document_hash: str


class ReidentifyResponse(BaseModel):
    reidentified_text: str
    replacement_count: int
