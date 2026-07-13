# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from solomon.currency.models import CredenceTier, KnowledgeItem, KnowledgeKind, Provenance, SourceKind
from solomon.store.sqlite import OutboxEventNotFoundError, SQLiteKnowledgeStore

OUTBOX_DUE = datetime(2027, 1, 1, tzinfo=timezone.utc)


def _item() -> KnowledgeItem:
    timestamp = datetime(2026, 7, 13, 8, 30, tzinfo=timezone.utc)
    return KnowledgeItem(
        id="item-1",
        kind=KnowledgeKind.HOUSE_VIEW,
        content="Structure X is compliant under Regulation R section 12.",
        provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref="memo-1"),
        valid_from=timestamp,
        ingested_at=timestamp,
        credence_tier=CredenceTier.FIRM_AUTHORITATIVE,
        last_verified_at=timestamp,
    )


def test_knowledge_changes_create_pending_canonical_outbox_events_atomically(tmp_path):
    store = SQLiteKnowledgeStore(tmp_path / "solomon.sqlite3")
    item = _item()

    store.write_item(item)
    pending = store.pending_outbox_events(available_before=OUTBOX_DUE)

    assert len(pending) == 1
    assert pending[0].event.aggregate_id == item.id
    assert pending[0].event.actor_id == "system:knowledge-store"
    assert pending[0].event.idempotency_key == pending[0].event.event_id
    with pytest.raises(sqlite3.IntegrityError):
        store.write_item(item)
    assert [record.event.event_id for record in store.pending_outbox_events(available_before=OUTBOX_DUE)] == [
        pending[0].event.event_id
    ]


def test_outbox_pending_read_delivery_acknowledgement_and_snapshot_restore(tmp_path):
    store = SQLiteKnowledgeStore(tmp_path / "solomon.sqlite3")
    store.write_item(_item())
    record = store.pending_outbox_events(available_before=OUTBOX_DUE)[0]

    completed = store.mark_outbox_delivered(record.event.event_id)
    snapshot = store.snapshot(tmp_path / "snapshot.json")
    restored = SQLiteKnowledgeStore.restore(snapshot, tmp_path / "restored.sqlite3")

    assert completed.delivered_at is not None
    assert completed.delivery_attempts == 1
    assert store.pending_outbox_events() == []
    assert restored.pending_outbox_events() == []
    with pytest.raises(OutboxEventNotFoundError):
        store.mark_outbox_delivered("missing")
    with pytest.raises(ValueError, match="positive"):
        store.pending_outbox_events(limit=0)
