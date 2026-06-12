# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from solomon.boundary.engine.client import BoundaryClient
from solomon.boundary.kaypoh import (
    BoundaryPolicy,
    BoundaryRefusedError,
    BoundaryUnavailableError,
    KaypohBoundary,
    check_placeholder_survival,
)
from solomon.currency.models import KnowledgeItem, KnowledgeKind, Provenance, SourceKind


@dataclass
class FakeResponse:
    classification: str = "SAFE"
    findings: list[dict[str, Any]] | None = None
    request_id: str | None = "req-1"
    pseudonymized_text: str = "Send [PERSON_1] the memo."
    mapping: list[dict[str, str]] | None = None
    document_hash: str = "a" * 64
    reidentified_text: str = "Send Jane the memo."
    replacement_count: int = 1


class FakeKaypohClient:
    def __init__(self) -> None:
        self.review_requests: list[dict[str, Any]] = []
        self.pseudonymize_requests: list[dict[str, Any]] = []
        self.fail = False

    def review(self, *args: Any, **kwargs: Any) -> FakeResponse:
        if self.fail:
            raise RuntimeError("down")
        self.review_requests.append(dict(kwargs["request"]))
        return FakeResponse(classification="HIGH_RISK", findings=[{"severity": "high"}])

    def pseudonymize(self, *args: Any, **kwargs: Any) -> FakeResponse:
        if self.fail:
            raise RuntimeError("down")
        self.pseudonymize_requests.append(dict(kwargs["request"]))
        return FakeResponse(mapping=[{"placeholder": "[PERSON_1]", "original_text": "Jane"}])

    def reidentify(self, *args: Any, **kwargs: Any) -> FakeResponse:
        if self.fail:
            raise RuntimeError("down")
        assert kwargs["mapping"] == [{"placeholder": "[PERSON_1]", "original_text": "Jane"}]
        return FakeResponse()

    def scrub_document(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("down")
        return {"document_base64": kwargs["document_base64"], "metadata_findings": []}


def _item() -> KnowledgeItem:
    return KnowledgeItem(
        id="item-1",
        kind=KnowledgeKind.NOTE,
        content="Acme confidential note",
        provenance=Provenance(source_kind=SourceKind.ASSOCIATE, source_ref="note"),
        matter_id="matter-1",
    )


def test_ingestion_gate_quarantines_and_captures_kaypoh_findings() -> None:
    client = FakeKaypohClient()
    boundary = KaypohBoundary(client, policy=BoundaryPolicy(unsafe_action="quarantine"))

    gated, review = boundary.review_for_ingest(_item(), source_jurisdiction="SG", destination_jurisdiction="US")

    assert review.action == "quarantine"
    assert gated.provenance.kaypoh_review_classification == "HIGH_RISK"
    assert gated.provenance.kaypoh_findings == [{"severity": "high"}]
    assert gated.metadata["kaypoh_quarantine"]["classification"] == "HIGH_RISK"
    assert client.review_requests[0]["source_jurisdiction"] == "SG"
    assert client.review_requests[0]["destination_jurisdiction"] == "US"


def test_ingestion_gate_can_refuse_by_policy() -> None:
    boundary = KaypohBoundary(FakeKaypohClient(), policy=BoundaryPolicy(unsafe_action="refuse"))

    with pytest.raises(BoundaryRefusedError):
        boundary.review_for_ingest(_item())


def test_sanitize_reidentify_uses_volatile_mapping_and_structured_tokens() -> None:
    client = FakeKaypohClient()
    boundary = KaypohBoundary(client)

    sanitized = boundary.sanitize_context("Send Jane the memo.", matter_id="matter-1")
    result = boundary.reidentify_response(sanitized.context_id, "Send [PERSON_1] the memo.")

    assert sanitized.sanitized_text == "Send [PERSON_1] the memo."
    assert sanitized.mapping_count == 1
    assert client.pseudonymize_requests[0]["persist_mapping"] is False
    assert client.pseudonymize_requests[0]["llm_input_mode"] == "structured_tokens"
    assert result.text == "Send Jane the memo."
    assert result.mapping_flushed is True
    assert boundary.volatile_mapping_count() == 0


def test_raw_text_egress_requires_matter_opt_in() -> None:
    boundary = KaypohBoundary(FakeKaypohClient())

    with pytest.raises(BoundaryRefusedError, match="raw_text"):
        boundary.sanitize_context("raw", matter_id="matter-1", input_mode="raw_text")

    allowed = KaypohBoundary(
        FakeKaypohClient(),
        policy=BoundaryPolicy(llm_input_mode="raw_text", raw_text_matter_opt_ins={"matter-1"}),
    )
    assert allowed.sanitize_context("raw", matter_id="matter-1").input_mode == "raw_text"


def test_boundary_fails_closed_when_kaypoh_is_unavailable() -> None:
    client = FakeKaypohClient()
    client.fail = True
    boundary = KaypohBoundary(client)

    with pytest.raises(BoundaryUnavailableError):
        boundary.review_for_ingest(_item())
    with pytest.raises(BoundaryUnavailableError):
        boundary.sanitize_context("text", matter_id="matter-1")
    with pytest.raises(BoundaryUnavailableError):
        boundary.scrub_document(document_base64="Zm9v", document_filename="memo.txt")


def test_placeholder_survival_flags_dropped_tokens() -> None:
    mapping = [
        {"placeholder": "[PERSON_1]", "original_text": "Jane"},
        {"placeholder": "[CLIENT_1]", "original_text": "Acme"},
    ]

    result = check_placeholder_survival("Memo for [PERSON_1]", mapping)

    assert result.ok is False
    assert result.present_placeholders == ["[PERSON_1]"]
    assert result.missing_placeholders == ["[CLIENT_1]"]


def test_vendored_boundary_exposes_kaypoh_required_surface_parity() -> None:
    client = BoundaryClient()

    capabilities = client.capabilities()

    for method in ["review", "pseudonymize", "anonymize", "redact", "reidentify", "scrub_document"]:
        assert hasattr(client, method)
    assert capabilities.surfaces == [
        "review",
        "pseudonymize",
        "anonymize",
        "redact",
        "reidentify",
        "documents/scrub",
    ]
    assert capabilities.privacy_operations == ["pseudonymize", "anonymize", "redact", "reidentify"]
    assert set(capabilities.jurisdiction_codes) == {
        "AE",
        "AU",
        "CN",
        "EU",
        "HK",
        "ID",
        "IN",
        "JP",
        "KR",
        "MY",
        "PH",
        "SA",
        "SEA",
        "SG",
        "TH",
        "UK",
        "US",
        "VN",
    }
    assert "mnpi_lexicon" in capabilities.detector_families
    assert "placeholder_rewrite" in capabilities.detector_families


def test_vendored_boundary_detects_expanded_pii_mnpi_and_jurisdiction_terms() -> None:
    client = BoundaryClient()

    response = client.review(
        request={
            "text": (
                "Send Dr Jane Tan S1234567D, passport number E1234567, DOB 01/02/1980, "
                "card 4111 1111 1111 1111, IP 192.168.1.10, and confidential Q1 guidance "
                "before announcement under UK MAR."
            ),
            "source_jurisdiction": "SG",
            "destination_jurisdiction": "UK",
        }
    )

    kinds = {finding.kind for finding in response.findings}
    assert response.classification == "HIGH_RISK"
    assert {
        "person",
        "national_id",
        "passport_number",
        "date_of_birth",
        "credit_card",
        "ip_address",
        "mnpi_or_high_risk_secret",
        "jurisdiction_strict_term",
    }.issubset(kinds)
    assert any(finding.jurisdiction == "UK" for finding in response.findings)


def test_anonymize_is_irreversible_and_redact_is_opaque() -> None:
    client = BoundaryClient()
    text = "Send Jane Tan at jane@example.com the $2.5 billion draft."

    anonymized = client.anonymize(text)
    redacted = client.redact(text)

    assert "Jane" not in anonymized.anonymized_text
    assert "jane@example.com" not in anonymized.anonymized_text
    assert anonymized.mapping_persisted is False
    assert anonymized.anonymization_mode == "placeholder_only"
    assert all(not hasattr(replacement, "original_text") for replacement in anonymized.replacements)
    assert "Jane" not in redacted.redacted_text
    assert "EMAIL" not in redacted.redacted_text
    assert redacted.redaction_style == "opaque_text_marker"
    assert redacted.mapping_persisted is False
