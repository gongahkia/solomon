from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from stonks_cli.vnext.events import (
    EventSeverity,
    StructuredEvent,
    create_structured_event,
    deserialize_structured_event,
    serialize_structured_event,
)
from stonks_cli.vnext.foundation import FrozenUTCClock, RunIdentity


def test_structured_event_is_utc_linked_to_run_and_immutable_from_input_changes():
    payload = {"asset": "BTC", "metrics": [{"score": 1.0}]}
    run = RunIdentity(UUID("12345678-1234-5678-1234-567812345678"), datetime(2026, 7, 14, 2, 0, tzinfo=UTC))

    event = create_structured_event(
        FrozenUTCClock(datetime(2026, 7, 14, 2, 1, tzinfo=UTC)),
        run,
        name="research.snapshot.created",
        payload=payload,
        event_id=UUID("87654321-4321-8765-4321-876543218765"),
    )
    payload["metrics"][0]["score"] = 0.0

    assert event.run_id == run.run_id
    assert event.occurred_at == datetime(2026, 7, 14, 2, 1, tzinfo=UTC)
    assert event.severity is EventSeverity.INFO
    assert event.payload["metrics"] == ({"score": 1.0},)


@pytest.mark.parametrize(
    ("name", "severity", "payload"),
    [
        ("Invalid event", EventSeverity.INFO, {}),
        ("research.failed", "error", {}),
        ("research.failed", EventSeverity.ERROR, {"api_token": "token-value"}),
        ("research.failed", EventSeverity.ERROR, {"score": float("nan")}),
        ("research.failed", EventSeverity.ERROR, {"nested": object()}),
    ],
)
def test_structured_event_rejects_malformed_or_sensitive_inputs(name, severity, payload):
    with pytest.raises((TypeError, ValueError)):
        StructuredEvent(
            UUID("87654321-4321-8765-4321-876543218765"),
            UUID("12345678-1234-5678-1234-567812345678"),
            datetime(2026, 7, 14, 2, 1, tzinfo=UTC),
            name,
            severity,
            payload,
        )


def test_structured_event_json_is_deterministic_and_round_trips():
    run = RunIdentity(UUID("12345678-1234-5678-1234-567812345678"), datetime(2026, 7, 14, 2, 0, tzinfo=UTC))
    event = create_structured_event(
        FrozenUTCClock(datetime(2026, 7, 14, 2, 1, tzinfo=UTC)),
        run,
        name="research.snapshot.created",
        severity=EventSeverity.WARNING,
        payload={"assets": ["BTC", "ETH"], "count": 2},
        event_id=UUID("87654321-4321-8765-4321-876543218765"),
    )

    serialized = serialize_structured_event(event)

    assert serialized == serialize_structured_event(event)
    assert deserialize_structured_event(serialized) == event


@pytest.mark.parametrize(
    "serialized",
    [
        "not-json",
        '{"version": 2}',
        '{"version": 1, "event_id": "87654321-4321-8765-4321-876543218765", "run_id": "12345678-1234-5678-1234-567812345678", "occurred_at": "2026-07-14T02:01:00Z", "name": "research.snapshot.created", "severity": "info", "payload": {"api_token": "token-value"}}',
    ],
)
def test_structured_event_json_rejects_malformed_or_sensitive_input(serialized):
    with pytest.raises(ValueError, match="invalid serialized event"):
        deserialize_structured_event(serialized)
