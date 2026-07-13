# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from solomon.events import DOMAIN_EVENT_SCHEMA_VERSION, DomainEventEnvelope


def _event(**changes: object) -> DomainEventEnvelope:
    values: dict[str, object] = {
        "event_type": "document.ingested",
        "aggregate_type": "source_document",
        "aggregate_id": "document-1",
        "actor_id": "system:filesystem-sync",
        "correlation_id": "sync-1",
        "idempotency_key": "source-1:memo-1:v2",
        "occurred_at": datetime(2026, 7, 13, 8, 30, tzinfo=timezone.utc),
        "payload": {"document_id": "document-1", "version": 2},
    }
    values.update(changes)
    return DomainEventEnvelope.model_validate(values)


def test_domain_event_envelope_has_required_audit_identity_and_stable_payload_hash():
    event = _event()
    same_payload = _event(payload={"version": 2, "document_id": "document-1"})

    assert event.schema_version == DOMAIN_EVENT_SCHEMA_VERSION
    assert event.event_version == 1
    assert event.occurred_at.tzinfo is timezone.utc
    assert event.payload_sha256 == same_payload.payload_sha256
    assert event.payload_sha256 == DomainEventEnvelope.payload_digest(event.payload)


def test_domain_event_envelope_rejects_payload_hash_tampering_and_missing_identity_fields():
    with pytest.raises(ValidationError, match="payload_sha256"):
        _event(payload_sha256="0" * 64)
    with pytest.raises(ValidationError):
        _event(actor_id="")
    with pytest.raises(ValidationError):
        _event(correlation_id="")
    with pytest.raises(ValidationError):
        _event(idempotency_key="")
