from __future__ import annotations

from pathlib import Path

from stonks_cli.vnext.events import EventSeverity, deserialize_structured_event
from stonks_cli.vnext.fixtures import (
    deterministic_fixture_event_jsonl,
    deterministic_fixture_events,
    deterministic_fixture_run,
)

ROOT = Path(__file__).resolve().parents[1]


def test_deterministic_vnext_fixture_builders_are_stable():
    events = deterministic_fixture_events()

    assert deterministic_fixture_run().run_id == events[0].run_id == events[1].run_id
    assert events[0].severity is EventSeverity.INFO
    assert events[1].severity is EventSeverity.WARNING
    assert deterministic_fixture_events() == events


def test_deterministic_event_jsonl_matches_checked_in_fixture_and_round_trips():
    jsonl = deterministic_fixture_event_jsonl()

    assert jsonl == (ROOT / "tests/fixtures/vnext/events.jsonl").read_text(encoding="utf-8")
    assert tuple(deserialize_structured_event(line) for line in jsonl.splitlines()) == deterministic_fixture_events()
