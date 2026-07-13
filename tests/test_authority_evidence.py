# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone

from solomon.workflow.models import AuthorityChangeEvent
from solomon.workflow.store import SQLiteWorkflowStore


def test_authority_events_persist_observed_version_effective_time_and_structured_diff(tmp_path):
    store = SQLiteWorkflowStore(tmp_path / "workflow.sqlite3")
    event = AuthorityChangeEvent(
        source_id="official-gazette",
        idempotency_key="regulation-r-12:v3",
        authority_id="authority:official-gazette:regulation-r-12",
        previous_version="v2",
        new_version="v3",
        changed_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
        evidence_url="https://gazette.test/regulation-r-12/v3",
        evidence_sha256="a" * 64,
        diff={"sections_changed": ["12", "14"], "summary": "expanded reporting scope"},
    )

    stored, created = store.record_authority_event(event)
    duplicate, duplicate_created = store.record_authority_event(event)

    assert created is True
    assert duplicate_created is False
    assert duplicate == stored
    assert stored.previous_version == "v2"
    assert stored.new_version == "v3"
    assert stored.changed_at == datetime(2026, 7, 13, tzinfo=timezone.utc)
    assert stored.evidence_url == "https://gazette.test/regulation-r-12/v3"
    assert stored.evidence_sha256 == "a" * 64
    assert stored.diff["sections_changed"] == ["12", "14"]
