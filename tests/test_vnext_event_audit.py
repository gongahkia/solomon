from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from stonks_cli.vnext.database import SQLiteConnectionFactory
from stonks_cli.vnext.errors import VNextInvariantError
from stonks_cli.vnext.event_audit import ImmutableEventAudit, ImmutableEventAuditReport
from stonks_cli.vnext.events import EventSeverity, StructuredEvent


def test_immutable_event_audit_persists_and_verifies_an_ordered_hash_chain(tmp_path):
    audit = ImmutableEventAudit(SQLiteConnectionFactory(tmp_path / "audit.sqlite3"))
    first = _event("00000000-0000-4000-8000-000000000001", 0)
    second = _event("00000000-0000-4000-8000-000000000002", 1)

    first_report = audit.append(first)
    second_report = audit.append(second)

    assert first_report.entry_count == 1
    assert second_report.entry_count == 2
    assert audit.verify() == second_report


def test_immutable_event_audit_rejects_duplicate_or_tampered_events(tmp_path):
    factory = SQLiteConnectionFactory(tmp_path / "audit.sqlite3")
    audit = ImmutableEventAudit(factory)
    event = _event("00000000-0000-4000-8000-000000000001", 0)
    audit.append(event)

    with pytest.raises(VNextInvariantError, match="duplicate"):
        audit.append(event)
    with factory.connect() as connection:
        connection.execute("UPDATE vnext_immutable_event_audit_entries SET event_json = ?", ("tampered",))
    with pytest.raises(VNextInvariantError, match="chain is broken"):
        audit.verify()


@pytest.mark.parametrize("event", [None, "event", {}])
def test_immutable_event_audit_fails_closed_for_malformed_event_input(event, tmp_path):
    audit = ImmutableEventAudit(SQLiteConnectionFactory(tmp_path / "audit.sqlite3"))

    with pytest.raises(TypeError, match="structured event"):
        audit.append(event)  # type: ignore[arg-type]


@pytest.mark.parametrize("entry_count,head_hash", [(-1, None), (0, "a" * 64), (1, None)])
def test_immutable_event_audit_report_rejects_malformed_data(entry_count, head_hash):
    with pytest.raises(ValueError):
        ImmutableEventAuditReport(entry_count, head_hash)


def _event(event_id: str, offset_minutes: int) -> StructuredEvent:
    return StructuredEvent(
        UUID(event_id),
        UUID("00000000-0000-4000-8000-000000000010"),
        datetime(2026, 7, 14, 3, tzinfo=UTC) + timedelta(minutes=offset_minutes),
        "reliability.audit.recorded",
        EventSeverity.INFO,
        {"count": offset_minutes},
    )
