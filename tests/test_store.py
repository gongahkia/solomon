# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from solomon.currency.models import (
    CredenceTier,
    CurrencyState,
    KnowledgeItem,
    KnowledgeKind,
    Provenance,
    SourceKind,
    new_uuid7,
)
from solomon.store.sqlite import ItemNotFoundError, SQLiteKnowledgeStore


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _item(item_id: str, content: str, ingested_at: datetime) -> KnowledgeItem:
    return KnowledgeItem(
        id=item_id,
        kind=KnowledgeKind.HOUSE_VIEW,
        content=content,
        provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref="memo-1", author="Partner A"),
        valid_from=ingested_at,
        ingested_at=ingested_at,
        credence_tier=CredenceTier.FIRM_AUTHORITATIVE,
        last_verified_at=ingested_at,
        verified_by="Partner A",
    )


def test_uuid7_fallback_is_time_orderable() -> None:
    first = new_uuid7()
    second = new_uuid7()

    assert first < second


def test_write_get_many_and_missing_item(tmp_path: Path) -> None:
    store = SQLiteKnowledgeStore(tmp_path / "solomon.sqlite3")
    item = _item("item-1", "2023 house view", _dt(2023, 1, 1))

    store.write_item(item)

    assert store.get_item("item-1") == item
    assert store.get_many() == [item]
    with pytest.raises(ItemNotFoundError):
        store.get_item("missing")


def test_supersede_closes_predecessor_without_deleting(tmp_path: Path) -> None:
    store = SQLiteKnowledgeStore(tmp_path / "solomon.sqlite3")
    predecessor = _item("item-1", "2023 house view", _dt(2023, 1, 1))
    successor = _item("item-2", "2025 replacement view", _dt(2025, 1, 1))
    store.write_item(predecessor)

    closed, written_successor = store.supersede("item-1", successor, superseded_at=_dt(2025, 1, 1))

    assert closed.currency_state is CurrencyState.SUPERSEDED
    assert closed.valid_to == _dt(2025, 1, 1)
    assert closed.successor_id == "item-2"
    assert written_successor.metadata["supersedes"] == "item-1"
    assert {item.id for item in store.get_many()} == {"item-1", "item-2"}
    assert store.get_many(include_states={CurrencyState.LIVE}) == [written_successor]


def test_as_of_reconstructs_historical_state(tmp_path: Path) -> None:
    store = SQLiteKnowledgeStore(tmp_path / "solomon.sqlite3")
    predecessor = _item("item-1", "2023 house view", _dt(2023, 1, 1))
    successor = _item("item-2", "2025 replacement view", _dt(2025, 1, 1))

    store.write_item(predecessor)
    store.supersede("item-1", successor, superseded_at=_dt(2025, 1, 1))

    before_change = store.as_of(_dt(2024, 1, 1))
    after_change = store.as_of(_dt(2026, 1, 1))

    assert [(item.id, item.currency_state) for item in before_change] == [("item-1", CurrencyState.LIVE)]
    assert [(item.id, item.currency_state) for item in after_change] == [
        ("item-1", CurrencyState.SUPERSEDED),
        ("item-2", CurrencyState.LIVE),
    ]


def test_snapshot_restore_and_rebuild_current_state(tmp_path: Path) -> None:
    db_path = tmp_path / "solomon.sqlite3"
    store = SQLiteKnowledgeStore(db_path)
    store.write_item(_item("item-1", "2023 house view", _dt(2023, 1, 1)))
    snapshot = store.snapshot(tmp_path / "snapshot.json")
    store.close()

    restored = SQLiteKnowledgeStore.restore(snapshot, tmp_path / "restored.sqlite3")
    assert restored.get_item("item-1").content == "2023 house view"

    restored.rebuild_current_state()
    assert restored.get_item("item-1").currency_state is CurrencyState.LIVE


def test_store_source_has_no_knowledge_item_delete_path() -> None:
    source = Path("src/solomon/store/sqlite.py").read_text(encoding="utf-8").lower()
    assert "delete from knowledge_items" not in source
    assert "delete from knowledge_events" not in source
