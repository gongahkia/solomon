# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from solomon.contracts import WebhookDelivery, WebhookEvent
from solomon.webhooks import (
    HMACWebhookDispatcher,
    SQLiteWebhookDeliveryStore,
    WebhookDeliveryError,
    WebhookDeliveryState,
)


@dataclass
class Response:
    status_code: int


class RecordingTransport:
    def __init__(self, responses: list[int | Exception]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, content: bytes, headers: dict[str, str]) -> Response:
        self.calls.append({"url": url, "content": content, "headers": headers})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return Response(status_code=response)


def _delivery() -> WebhookDelivery:
    return WebhookDelivery(
        event=WebhookEvent(
            event_type="review_task.resolved",
            event_id="event-1",
            occurred_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
            payload={"task_id": "task-1"},
        ),
        target_url="https://hooks.example.test/solomon",
        idempotency_key="review-task:task-1:resolved",
    )


def test_dispatcher_signs_delivers_inspects_and_deduplicates(tmp_path: Path) -> None:
    secret = "test-" + "webhook-secret"
    transport = RecordingTransport([202])
    dispatcher = HMACWebhookDispatcher(
        signing_secret=secret,
        store=SQLiteWebhookDeliveryStore(tmp_path / "webhooks.sqlite3"),
        transport=transport,
    )

    delivered = dispatcher.deliver(_delivery())
    replay = dispatcher.deliver(_delivery())
    call = transport.calls[0]
    conflicting = _delivery().model_copy(update={"event": _delivery().event.model_copy(update={"event_id": "event-2"})})

    assert delivered.status_code == 202
    assert delivered.attempts == 1
    assert replay.idempotent_replay is True
    assert len(transport.calls) == 1
    with pytest.raises(WebhookDeliveryError, match="different event payload"):
        dispatcher.deliver(conflicting)
    assert json.loads(call["content"]) == _delivery().event.model_dump(mode="json")
    expected = hmac.new(secret.encode(), call["content"], hashlib.sha256).hexdigest()
    assert call["headers"]["X-Solomon-Signature"] == f"sha256={expected}"
    inspected = dispatcher.inspect(delivered.delivery_id)
    assert inspected.state is WebhookDeliveryState.DELIVERED
    assert dispatcher.list_deliveries(state=WebhookDeliveryState.DELIVERED) == [inspected]


def test_dispatcher_retries_transient_failures_and_stops_on_forbidden(tmp_path: Path) -> None:
    transient = RecordingTransport([500, ConnectionError("offline"), 204])
    dispatcher = HMACWebhookDispatcher(
        signing_secret="test-" + "webhook-secret",
        store=SQLiteWebhookDeliveryStore(tmp_path / "transient.sqlite3"),
        transport=transient,
    )
    delivered = dispatcher.deliver(_delivery())

    assert delivered.status_code == 204
    assert delivered.attempts == 3
    assert len(transient.calls) == 3

    forbidden = RecordingTransport([403])
    failed_dispatcher = HMACWebhookDispatcher(
        signing_secret="test-" + "webhook-secret",
        store=SQLiteWebhookDeliveryStore(tmp_path / "forbidden.sqlite3"),
        transport=forbidden,
    )
    failed = failed_dispatcher.deliver(_delivery())

    assert failed.status_code == 403
    assert failed.attempts == 1
    assert failed_dispatcher.inspect(failed.delivery_id).state is WebhookDeliveryState.FAILED


def test_dispatcher_rejects_unsafe_targets(tmp_path: Path) -> None:
    dispatcher = HMACWebhookDispatcher(
        signing_secret="test-" + "webhook-secret",
        store=SQLiteWebhookDeliveryStore(tmp_path / "unsafe.sqlite3"),
        transport=RecordingTransport([]),
    )
    invalid = _delivery().model_copy(update={"target_url": "http://127.0.0.1/hooks"})

    with pytest.raises(WebhookDeliveryError, match="https"):
        dispatcher.deliver(invalid)
