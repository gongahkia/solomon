# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from solomon.api.service import IngestRequest, SolomonService
from solomon.api.service_models import DocumentSourceRequest, RecallRequest, VerificationRequest
from solomon.authority_webhooks import AuthorityWebhookIntake
from solomon.config import Settings
from solomon.connectors import ConnectorConfiguration, SecretReference, SecretReferenceProvider
from solomon.contracts import AuthoritySource, AuthoritySourceKind, WebhookDelivery, WebhookEvent
from solomon.currency.engine import VerificationOutcome
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.mcp.tools.runtime import SolomonMCPRuntime
from solomon.sources.models import DocumentSourceKind
from solomon.telemetry import SolomonTelemetry
from solomon.webhooks import HMACWebhookDispatcher, SQLiteWebhookDeliveryStore


@dataclass
class _Response:
    status_code: int


class _WebhookTransport:
    def post(self, _url: str, *, content: bytes, headers: dict[str, str]) -> _Response:
        assert content
        assert headers["X-Solomon-Signature"].startswith("sha256=")
        return _Response(status_code=202)


def test_telemetry_traces_operational_surfaces_without_content(tmp_path: Path) -> None:
    exporter = InMemorySpanExporter()
    telemetry = SolomonTelemetry(enabled=True, span_exporter=exporter)
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal", telemetry=telemetry)
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "memo.txt").write_text("connector trace document", encoding="utf-8")
    service.register_document_source(
        DocumentSourceRequest(name="internal", kind=DocumentSourceKind.FILESYSTEM, root_ref=str(source_root))
    )
    source = service.document_store.list_sources()[0]
    service.sync_document_source(source.id)
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="confidential telemetry position",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-telemetry",
            matter_id="matter-a",
            client_id="client-a",
        )
    )
    service.recall(RecallRequest(query="telemetry", matter_id="matter-a", client_id="client-a"))
    service.record_verification(
        item.id,
        VerificationRequest(by="lawyer-a", outcome=VerificationOutcome.REAFFIRM, basis="reviewed", source_ref="memo"),
    )
    SolomonMCPRuntime(service).check_currency(knowledge_item_id=item.id)
    dispatcher = HMACWebhookDispatcher(
        signing_secret="test-" + "webhook-secret",
        store=SQLiteWebhookDeliveryStore(tmp_path / "webhooks.sqlite3"),
        transport=_WebhookTransport(),
        telemetry=telemetry,
    )
    dispatcher.deliver(
        WebhookDelivery(
            event=WebhookEvent(event_type="review_task.resolved", event_id="event-1", payload={}),
            target_url="https://hooks.example.test/solomon",
            idempotency_key="event-1",
        )
    )
    assert telemetry.force_flush() is True
    spans = exporter.get_finished_spans()
    names = {span.name for span in spans}

    assert {
        "solomon.connector.register",
        "solomon.connector.sync",
        "solomon.ingestion.ingest",
        "solomon.boundary.review",
        "solomon.retrieval.recall",
        "solomon.review.record_verification",
        "solomon.mcp.tool",
        "solomon.webhook.deliver",
    }.issubset(names)
    attribute_texts = [str(span.attributes or {}) for span in spans]
    assert "confidential telemetry position" not in str(attribute_texts)
    assert all("memo-telemetry" not in attributes for attributes in attribute_texts)


def test_telemetry_traces_inbound_webhook_without_payload() -> None:
    exporter = InMemorySpanExporter()
    telemetry = SolomonTelemetry(enabled=True, span_exporter=exporter)
    body = (
        b'{"idempotency_key":"event-1","authority_id":"authority-1","new_version":"v2",'
        b'"changed_at":"2026-07-13T00:00:00Z","diff":{"private":"payload"}}'
    )
    source = AuthoritySource(
        id="authority-source",
        name="authority source",
        kind=AuthoritySourceKind.WEBHOOK,
        root_ref="https://authority.example.test/webhook",
        config=ConnectorConfiguration(
            secret_references={
                "webhook_signing_secret": SecretReference(
                    provider=SecretReferenceProvider.VAULT,
                    reference="kv/authority/webhook",
                )
            }
        ),
    )
    secret = "webhook-secret"  # noqa: S105
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    AuthorityWebhookIntake(lambda _reference: secret, telemetry).parse(source, body, signature)

    assert telemetry.force_flush() is True
    span = exporter.get_finished_spans()[-1]
    assert span.name == "solomon.webhook.intake"
    assert "payload" not in str(span.attributes or {})


def test_telemetry_marks_failures_and_validates_self_hosted_endpoint() -> None:
    exporter = InMemorySpanExporter()
    telemetry = SolomonTelemetry(enabled=True, span_exporter=exporter)

    with pytest.raises(RuntimeError, match="failed operation"):
        with telemetry.span("solomon.test.failure"):
            raise RuntimeError("failed operation")
    assert telemetry.force_flush() is True
    failure = exporter.get_finished_spans()[-1]
    assert failure.status.status_code.name == "ERROR"
    assert "failed operation" not in str(failure.events)
    assert Settings(
        telemetry_enabled=True,
        telemetry_otlp_endpoint="http://127.0.0.1:4318/v1/traces",
    ).public_diagnostics()["telemetry_otlp_configured"] is True
    with pytest.raises(ValueError, match="requires SOLOMON_TELEMETRY_ENABLED"):
        Settings(telemetry_otlp_endpoint="http://127.0.0.1:4318/v1/traces")
