from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from stonks_cli.vnext.events import EventSeverity, StructuredEvent, create_structured_event, serialize_structured_event
from stonks_cli.vnext.foundation import FrozenUTCClock, RunIdentity

FIXTURE_RUN_ID = UUID("00000000-0000-4000-8000-000000000001")
FIXTURE_EVENT_IDS = (
    UUID("00000000-0000-4000-8000-000000000011"),
    UUID("00000000-0000-4000-8000-000000000012"),
)
FIXTURE_RUN_STARTED_AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def deterministic_fixture_run() -> RunIdentity:
    return RunIdentity(FIXTURE_RUN_ID, FIXTURE_RUN_STARTED_AT)


def deterministic_fixture_events() -> tuple[StructuredEvent, ...]:
    run = deterministic_fixture_run()
    return (
        create_structured_event(
            FrozenUTCClock(datetime(2026, 1, 2, 3, 4, 6, tzinfo=UTC)),
            run,
            name="research.snapshot.created",
            payload={"asset": "BTC", "snapshot_count": 2},
            event_id=FIXTURE_EVENT_IDS[0],
        ),
        create_structured_event(
            FrozenUTCClock(datetime(2026, 1, 2, 3, 4, 7, tzinfo=UTC)),
            run,
            name="research.source.stale",
            severity=EventSeverity.WARNING,
            payload={"age_seconds": 31, "source": "fixture"},
            event_id=FIXTURE_EVENT_IDS[1],
        ),
    )


def deterministic_fixture_event_jsonl() -> str:
    return "\n".join(serialize_structured_event(event) for event in deterministic_fixture_events()) + "\n"
